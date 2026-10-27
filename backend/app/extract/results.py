"""Quarterly results: first cut of Revenue, EBITDA, PBT and PAT, QoQ and YoY.

Division of labour:
  * code finds the results-table pages (keyword scoring, free) and cuts a 2-4 page PDF;
  * the cheap model reads those pages, which works on scans, and copies numbers as printed;
  * code does everything else: units, period matching, EBITDA, growth, margins, validation.
If validation fails, the same job is retried once on the strong model with more pages."""
import calendar
import logging
import re
from datetime import date

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.finance.calc import margin, pct_change, to_crore
from app.llm.client import generate, pdf_part
from app.models import Announcement, Company, FinancialMetric
from app.extract.documents import fetch_pdf, page_texts, subset_pdf

log = logging.getLogger(__name__)

PAGE_SIGNALS = {"revenue from operations": 3, "profit before tax": 3, "finance cost": 2,
                "depreciation": 2, "interest earned": 2, "other income": 1, "total income": 1,
                "net profit": 1, "tax expense": 1, "consolidated": 1}
MIN_PAGE_SCORE = 6

# The model only transcribes table rows (label as printed + one value per column); mapping
# labels to fields is code. A small model is far more reliable at copying than at filling a
# wide schema: with field-per-line it silently dropped PBT/PAT on real filings.
SCHEMA = {"type": "object", "properties": {"statements": {"type": "array", "items": {
    "type": "object", "properties": {
        "basis": {"type": "string", "enum": ["consolidated", "standalone"]},
        "unit": {"type": "string", "description": "unit exactly as printed, e.g. '₹ crore', 'INR million'"},
        "page": {"type": "integer", "description": "1-based page number in the attached PDF"},
        "columns": {"type": "array", "items": {"type": "object", "properties": {
            "period_end": {"type": "string", "description": "YYYY-MM-DD"},
            "period_type": {"type": "string", "enum": ["quarter", "half_year", "nine_months", "year"]}},
            "required": ["period_end", "period_type"]}},
        "rows": {"type": "array", "items": {"type": "object", "properties": {
            "label": {"type": "string"},
            "values": {"type": "array", "items": {"type": "number", "nullable": True}}},
            "required": ["label", "values"]}}},
    "required": ["basis", "unit", "columns", "rows"]}}}, "required": ["statements"]}

WANTED_ROWS = ("Revenue from operations (the total line) or Interest earned, Other income, Total income, "
               "Finance costs, Depreciation and amortisation, Profit before exceptional items and tax, "
               "Exceptional items, Profit before tax, Tax expense (total), Net profit / Profit for the "
               "period, Profit attributable to owners of the company")

SYSTEM = ("You transcribe the statement of profit and loss from Indian listed-company results filings. "
          "For each statement (consolidated and/or standalone), list its columns left to right, then "
          f"copy these rows: {WANTED_ROWS}. Copy labels and numbers exactly as printed, one value per "
          "column, in column order, in the table's own unit. Numbers in parentheses are negative; use "
          "null for a blank cell. Never compute, sum or infer a value.")

# label -> field. Order matters: "before exceptional" must win over "before tax".
ROW_FIELDS = [
    ("profit_before_exceptional_items_and_tax", r"before exceptional"),
    ("revenue_from_operations", r"revenue from operations|^interest earned|interest income"),
    ("other_income", r"^other income"),
    ("total_income", r"^total income"),
    ("finance_costs", r"finance cost|interest expended"),
    ("depreciation_amortisation", r"depreciation"),
    ("exceptional_items", r"^exceptional"),
    ("profit_before_tax", r"before tax"),
    ("tax_expense", r"tax expense"),
    ("net_profit_attributable_to_owners", r"owners|equity holders|shareholders of the"),
    ("net_profit", r"(net )?(profit|loss).*(for the|after tax)|^net profit"),
]
EXCLUDE_ROW = re.compile(r"comprehensive|non-controlling|minority|per share|eps", re.I)


def rows_to_periods(st: dict) -> list[dict]:
    """Map transcribed rows onto one dict per column. First labelled row with a value wins,
    except that 'Total revenue from operations' beats a bare 'Revenue from operations' header."""
    cols = st.get("columns") or []
    periods = [{"period_end": c.get("period_end"), "period_type": c.get("period_type")} for c in cols]
    for row in st.get("rows") or []:
        label = (row.get("label") or "").strip().lower()
        values = row.get("values") or []
        if not label or EXCLUDE_ROW.search(label) or not any(v is not None for v in values):
            continue
        field = next((f for f, p in ROW_FIELDS if re.search(p, label)), None)
        if field is None:
            continue
        override = field == "revenue_from_operations" and label.startswith("total")
        for i, p in enumerate(periods):
            if i < len(values) and values[i] is not None and (field not in p or override):
                p[field] = values[i]
    return periods


# ---------- deterministic helpers ----------
def fiscal_quarter(d: date) -> str:
    """Indian fiscal year runs April-March: quarter ended 30 Sep 2026 is Q2FY27."""
    fy = d.year + 1 if d.month >= 4 else d.year
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(d.month)
    if q is None:
        raise ValueError(f"{d} is not a quarter end")
    return f"Q{q}FY{fy % 100:02d}"


def months_back(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - n, 12)
    return date(y, m + 1, calendar.monthrange(y, m + 1)[1])


def parse_unit(printed: str) -> str:
    s = printed.lower()
    for pattern, unit in ((r"crore|\bcr\b", "crore"), (r"lakh|\blac", "lakh"), (r"million|\bmn\b", "million"),
                          (r"billion|\bbn\b", "billion"), (r"thousand|'000|000s", "thousand")):
        if re.search(pattern, s):
            return unit
    raise ValueError(f"unrecognised unit {printed!r}")


def candidate_pages(texts: list[str], limit: int) -> list[int]:
    scored = []
    for i, t in enumerate(texts):
        low = t.lower()
        score = sum(w for k, w in PAGE_SIGNALS.items() if k in low)
        if score >= MIN_PAGE_SCORE:
            scored.append((score, i))
    if not scored:  # pure image scan: no text to score, show the model the front of the filing
        return list(range(min(len(texts), limit + 2)))
    return sorted(i for _, i in sorted(scored, reverse=True)[:limit])


def _date(s: str) -> date | None:
    try:
        return date.fromisoformat(s[:10])
    except (TypeError, ValueError):
        return None


def _ebitda(p: dict) -> float | None:
    """EBITDA = profit before exceptional items & tax + finance costs + D&A - other income."""
    base = p.get("profit_before_exceptional_items_and_tax")
    if base is None:
        base = p.get("profit_before_tax")
    parts = [base, p.get("finance_costs"), p.get("depreciation_amortisation")]
    if any(v is None for v in parts):
        return None
    return parts[0] + parts[1] + parts[2] - (p.get("other_income") or 0)


def _metrics(p: dict, unit: str, financial: bool) -> dict:
    def cr(v):
        return None if v is None else round(to_crore(v, unit), 2)
    revenue = p.get("revenue_from_operations")
    if revenue is None and financial:
        revenue = p.get("total_income")
    pat = p.get("net_profit_attributable_to_owners")
    if pat is None:
        pat = p.get("net_profit")
    return {"revenue": cr(revenue), "ebitda": None if financial else cr(_ebitda(p)),
            "pbt": cr(p.get("profit_before_tax")), "pat": cr(pat)}


def build_results(raw: dict, financial: bool) -> tuple[dict | None, list[str]]:
    """Choose a statement, line up current / previous / year-ago quarters, compute changes."""
    issues: list[str] = []
    best = None
    for st in raw.get("statements") or []:
        quarters = {d: p for p in rows_to_periods(st)
                    if p.get("period_type") == "quarter" and (d := _date(p.get("period_end")))}
        if len(quarters) < 2:
            continue
        rank = (st.get("basis") == "consolidated", len(quarters))
        if best is None or rank > best[0]:
            best = (rank, st, quarters)
    if best is None:
        return None, ["no statement with at least two quarterly columns"]
    _, st, quarters = best
    try:
        unit = parse_unit(st.get("unit") or "")
    except ValueError as exc:
        return None, [str(exc)]

    cur_d = max(quarters)
    cur = _metrics(quarters[cur_d], unit, financial)
    prev_q, yoy_q = quarters.get(months_back(cur_d, 3)), quarters.get(months_back(cur_d, 12))
    prev = _metrics(prev_q, unit, financial) if prev_q else None
    yoy = _metrics(yoy_q, unit, financial) if yoy_q else None

    for name in ("revenue", "pbt", "pat"):
        if cur[name] is None:
            issues.append(f"missing {name} for the current quarter")
    if cur["revenue"] is not None and cur["revenue"] <= 0:
        issues.append("current revenue is not positive")
    if cur["pbt"] and cur["pat"] and abs(cur["pat"]) > abs(cur["pbt"]) * 1.6 + 1:
        issues.append("PAT is implausibly large relative to PBT")
    if prev is None and yoy is None:
        issues.append("no comparable quarter found")

    metrics = {}
    for name in ("revenue", "ebitda", "pbt", "pat"):
        metrics[name] = {
            "current_cr": cur[name],
            "prev_cr": prev[name] if prev else None,
            "year_ago_cr": yoy[name] if yoy else None,
            "qoq": pct_change(cur[name], prev[name] if prev else None).as_dict(),
            "yoy": pct_change(cur[name], yoy[name] if yoy else None).as_dict(),
        }
    margins = {}
    for name in ("ebitda", "pat"):
        now = margin(cur[name], cur["revenue"])
        then = margin(yoy[name], yoy["revenue"]) if yoy else None
        margins[name] = {"current_pct": None if now is None else round(now, 1),
                         "year_ago_pct": None if then is None else round(then, 1),
                         "change_pp": None if now is None or then is None else round(now - then, 1)}
    return {
        "period": fiscal_quarter(cur_d), "period_end": cur_d.isoformat(),
        "prev_period": fiscal_quarter(months_back(cur_d, 3)) if prev else None,
        "year_ago_period": fiscal_quarter(months_back(cur_d, 12)) if yoy else None,
        "basis": st.get("basis"), "unit_as_printed": st.get("unit"), "page": st.get("page"),
        "metrics": metrics, "margins": margins,
        "ebitda_definition": None if financial else
        "PBT before exceptional items + finance costs + D&A - other income",
        "notes": ["EBITDA is not meaningful for banks/NBFCs"] if financial else [],
    }, issues


def fmt_cr(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"₹{v:,.0f} cr" if abs(v) >= 100 else f"₹{v:,.1f} cr"


def _chg(c: dict) -> str:
    if c["value"] is not None:
        return f"{c['value']:+.1f}%"
    return c["note"] or "n/a"


def results_line(r: dict) -> str:
    m, mg = r["metrics"], r["margins"]
    parts = [f"Revenue {fmt_cr(m['revenue']['current_cr'])} ({_chg(m['revenue']['yoy'])} YoY, "
             f"{_chg(m['revenue']['qoq'])} QoQ)"]
    if mg["ebitda"]["current_pct"] is not None:
        then = mg["ebitda"]["year_ago_pct"]
        parts.append(f"EBITDA margin {mg['ebitda']['current_pct']}%" + (f" (vs {then}%)" if then is not None else ""))
    parts.append(f"PAT {fmt_cr(m['pat']['current_cr'])} ({_chg(m['pat']['yoy'])} YoY)")
    return " · ".join(parts)


def results_verdict(r: dict) -> str:
    rev, pat = r["metrics"]["revenue"]["yoy"]["value"], r["metrics"]["pat"]["yoy"]["value"]
    pat_note = r["metrics"]["pat"]["yoy"]["note"]
    dm = r["margins"]["ebitda"]["change_pp"]
    if pat_note == "turned to a loss":
        return "Swung to a loss versus a profit a year ago."
    if pat_note == "turned positive from a loss":
        return "Back to profit from a loss a year ago."
    if rev is None or pat is None:
        return "Headline numbers are in; year-ago comparison unavailable."
    if rev > 0 and pat < 0:
        tail = f" EBITDA margin {dm:+.1f}pp." if dm is not None else ""
        return f"Revenue grew but profit fell: costs rose faster than sales.{tail}"
    if rev >= 10 and pat >= 10:
        return "Strong quarter: revenue and profit both up double digits year on year."
    if rev < 0 and pat < 0:
        return "Revenue and profit both down year on year."
    if pat > rev + 5:
        return "Profit grew faster than revenue: margins expanded."
    return "Steady quarter: growth broadly in line across the P&L."


def numbers_in_text(r: dict, raw_period: dict | None, texts: list[str]) -> float | None:
    """Share of extracted current-quarter figures found verbatim in the PDF text layer.
    A cheap hallucination check for digital PDFs; None for scans with no usable text."""
    blob = re.sub(r"[,\s]", "", " ".join(texts))
    if len(blob) < 500 or not raw_period:
        return None
    vals = [v for k, v in raw_period.items() if isinstance(v, (int, float)) and k != "period_type"]
    if not vals:
        return None
    hits = sum(1 for v in vals if (f"{abs(v):.2f}".rstrip("0").rstrip(".") in blob))
    return round(hits / len(vals), 2)


def _store_metrics(db: Session, ann: Announcement, r: dict, doc_id: int) -> None:
    for name, m in r["metrics"].items():
        for period, value in ((r["period"], m["current_cr"]), (r["prev_period"], m["prev_cr"]),
                              (r["year_ago_period"], m["year_ago_cr"])):
            if period is None or value is None:
                continue
            stmt = insert(FinancialMetric).values(
                company_id=ann.company_id, metric=name, period=period, value_cr=value,
                basis=r["basis"], source_document_id=doc_id, source_announcement_id=ann.id,
                source_location=f"results filing p.{r.get('page')}")
            db.execute(stmt.on_conflict_do_update(
                index_elements=["company_id", "metric", "period", "basis"],
                set_={"value_cr": stmt.excluded.value_cr, "source_document_id": doc_id,
                      "source_announcement_id": ann.id, "source_location": stmt.excluded.source_location}))


def extract_results(db: Session, ann: Announcement) -> dict:
    company = db.get(Company, ann.company_id)
    doc, data = fetch_pdf(db, company.id, ann.document_url, "results", ann.summary or ann.title)
    texts = page_texts(data)
    attempts = []
    for tier, limit in (("cheap", 4), ("strong", 8)):
        pages = candidate_pages(texts, limit)
        res = generate(db, "results_extract",
                       [pdf_part(subset_pdf(data, pages)),
                        {"text": f"Company: {company.name}. Extract the results statements."}],
                       tier=tier, system=SYSTEM, schema=SCHEMA, thinking="low")
        built, issues = build_results(res.data, company.is_financial)
        attempts.append({"model": res.model, "pages": [p + 1 for p in pages], "cached": res.cached,
                         "cost_usd": round(res.cost_usd, 6), "issues": issues})
        if built and not issues:
            break
    if not built or issues:
        raise ValueError(f"results extraction failed validation: {issues}")

    # map the model's page number (within the subset) back to the original document
    if built.get("page") and 1 <= built["page"] <= len(pages):
        built["page"] = pages[built["page"] - 1] + 1
    raw_cur = next((p for st in res.data["statements"] if st.get("basis") == built["basis"]
                    for p in rows_to_periods(st) if (p.get("period_end") or "")[:10] == built["period_end"]
                    and p.get("period_type") == "quarter"), None)
    built["verified_in_text"] = numbers_in_text(built, raw_cur, [texts[i] for i in pages])
    built["line"] = results_line(built)
    built["verdict"] = results_verdict(built)
    built["source"] = {"document_id": doc.id, "url": ann.document_url}
    built["attempts"] = attempts
    _store_metrics(db, ann, built, doc.id)
    doc.period = built["period"]
    doc.status = "extracted"
    return built
