"""Promised vs delivered. Code lines each guidance statement up against reported numbers and
decides met / missed / exceeded / on track; the strong model only writes the read-across,
from that table, citing row ids. It never sees raw documents or does arithmetic here."""
import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.finance.calc import compare_to_guidance, margin, pct_change
from app.llm.client import generate
from app.models import FinancialDocument, FinancialMetric, ManagementGuidance

COMPARABLE = {"revenue_growth", "pat_growth", "ebitda_margin"}

# FINN measures reported, all-in rupee growth. A target stated on another measure is a different
# number; scoring it against reported revenue would manufacture a verdict.
OTHER_MEASURE = [
    (re.compile(r"constant[- ]currency|\bcc\b", re.I), "constant-currency target; FINN measures reported rupee revenue"),
    (re.compile(r"organic", re.I), "organic growth; reported revenue includes acquisitions"),
    (re.compile(r"price growth|volume growth|\bu[vs]g\b|underlying (?:volume|sales)", re.I),
     "a price or volume component, not total revenue"),
    (re.compile(r"system growth|credit growth|industry growth|market growth|\bGDP\b", re.I),
     "an industry-wide figure, not the company's own"),
]
# a growth target is scored only when the quote names the line; "we'll grow 15%" could be volume.
# Consumer companies say "value growth" for sales, as against volume growth.
NAMES_LINE = {"revenue_growth": re.compile(r"revenue|sales|top[- ]?line|turnover|income|value growth", re.I),
              "pat_growth": re.compile(r"profit|PAT|earnings|bottom[- ]?line", re.I)}
# Indian IT and others quote "operating margin" after depreciation (EBIT); EBITDA is before it
EBIT = re.compile(r"\bEBIT\b(?!DA)|operating margin", re.I)

NARRATIVE_SCHEMA = {"type": "object", "properties": {
    "verdict": {"type": "string", "enum": ["delivers", "mixed", "over_promises", "too_early"]},
    "summary": {"type": "string", "description": "3-5 sentences"},
    "highlights": {"type": "array", "items": {"type": "object", "properties": {
        "row_ids": {"type": "array", "items": {"type": "integer"}},
        "point": {"type": "string"}}, "required": ["row_ids", "point"]}}},
    "required": ["verdict", "summary", "highlights"]}

NARRATIVE_SYSTEM = ("You are a buy-side analyst judging management credibility. You get a table of what "
                    "management guided on earnings calls and what was later reported. Use only the rows "
                    "given: no outside knowledge, no new numbers, no arithmetic. Status values were computed "
                    "by code and are authoritative. Be specific and concise; refer to rows by id.")


def _q(period: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"Q([1-4])FY(\d{2})", period)
    return (int(m.group(2)), int(m.group(1))) if m else None


def actuals(db: Session, company_id: int) -> tuple[str | None, dict]:
    """{(fy, q): {metric: value_cr}} for the basis with the most quarterly revenue history."""
    rows = db.scalars(select(FinancialMetric).where(FinancialMetric.company_id == company_id)).all()
    by_basis: dict = {}
    for r in rows:
        key = _q(r.period)
        if key:
            by_basis.setdefault(r.basis, {}).setdefault(key, {})[r.metric] = r.value_cr
    if not by_basis:
        return None, {}
    basis = max(by_basis, key=lambda b: sum(1 for v in by_basis[b].values() if "revenue" in v))
    return basis, by_basis[basis]


def _quarters_for(period: str) -> list[tuple[int, int]] | None:
    m = re.fullmatch(r"(Q[1-4]|H[12])?FY(\d{2})", period or "")
    if not m:
        return None
    fy, part = int(m.group(2)), m.group(1)
    if part is None:
        qs = [1, 2, 3, 4]
    elif part.startswith("H"):
        qs = [1, 2] if part == "H1" else [3, 4]
    else:
        qs = [int(part[1])]
    return [(fy, q) for q in qs]


def _sum(series: dict, quarters: list, metric: str) -> float | None:
    vals = [series.get(q, {}).get(metric) for q in quarters]
    return None if any(v is None for v in vals) else sum(vals)


def _margin_metric(series: dict) -> str:
    """screener's operating profit gives a consistent multi-quarter series; else FINN's EBITDA."""
    have = Counter(m for v in series.values() for m in v)
    return "operating_profit" if have["operating_profit"] >= have["ebitda"] else "ebitda"


def _is_ebit(statement: str) -> bool:
    return bool(EBIT.search(statement)) and not re.search(r"EBITDA", statement, re.I)


def measure(g: ManagementGuidance, series: dict, ebit_ranges: frozenset = frozenset()) -> dict:
    """Actual for the guided metric over the guided period (or the reported part of it)."""
    if g.metric not in COMPARABLE:
        return {"status": "not_comparable", "reason": "not a reported P&L line; judge from later calls"}
    if g.scope == "segment":
        # e.g. L&T guides its Projects & Manufacturing margin, not the group's; scoring that
        # against group numbers would manufacture a false "exceeded"
        return {"status": "not_comparable", "reason": f"segment-level guidance ({g.segment or 'segment'}); "
                                                      "FINN scores company-level targets only"}
    if g.guidance_type != "explicit_numeric" or g.target_low is None or g.target_unit != "pct":
        return {"status": "not_comparable", "reason": "no numeric target"}
    if g.metric in NAMES_LINE and not NAMES_LINE[g.metric].search(g.statement):
        return {"status": "not_comparable",
                "reason": f"the quote doesn't say {'revenue' if g.metric == 'revenue_growth' else 'profit'} "
                          "is what grows; FINN won't guess"}
    if g.metric in ("revenue_growth", "pat_growth"):
        for rx, reason in OTHER_MEASURE:
            if rx.search(g.statement):
                return {"status": "not_comparable", "reason": reason}
    target = _quarters_for(g.target_period)
    if not target:
        return {"status": "not_comparable", "reason": "no specific period"}
    reported = [q for q in target if "revenue" in series.get(q, {})]
    if not reported:
        return {"status": "pending", "reason": f"no reported quarter of {g.target_period} yet"}
    partial = len(reported) < len(target)
    if partial and reported != target[:len(reported)]:
        return {"status": "not_comparable", "reason": "gaps in reported quarters"}
    prior = [(fy - 1, q) for fy, q in reported]
    measured_as = None
    if g.metric == "ebitda_margin":
        m = _margin_metric(series)
        profit = _sum(series, reported, m)
        # "margin guidance is maintained at 20-22%" inherits the definition used for that range elsewhere
        if _is_ebit(g.statement) or (g.target_low, g.target_high) in ebit_ranges:
            dep = _sum(series, reported, "depreciation")
            if profit is None or dep is None or m != "operating_profit":
                return {"status": "not_comparable",
                        "reason": "EBIT (after-depreciation) target; depreciation not available to measure it"}
            profit, measured_as = profit - dep, "EBIT margin: operating profit less depreciation, over revenue"
        else:
            measured_as = "operating profit over revenue" if m == "operating_profit" else "EBITDA over revenue"
        actual = margin(profit, _sum(series, reported, "revenue"))
    else:
        metric = "revenue" if g.metric == "revenue_growth" else "pat"
        actual = pct_change(_sum(series, reported, metric), _sum(series, prior, metric)).value
    if actual is None:
        return {"status": "not_comparable", "reason": "missing figures for the period"}
    cmp = compare_to_guidance(round(actual, 1), g.target_low, g.target_high)
    fy = reported[0][0]
    if len(reported) == 4:
        span = f"FY{fy}"
    else:  # e.g. "Q1+Q2FY27" for the reported part of a full-year target
        span = "+".join(f"Q{q}" for _, q in reported) + f"FY{fy}"
    status = cmp["status"]
    if partial:
        status = "on_track" if status in ("met", "exceeded") else "behind"
    return {"status": status, "actual": round(actual, 1), "gap": cmp["gap"], "measured_over": span,
            "partial": partial, **({"measured_as": measured_as} if measured_as else {})}


def guidance_table(db: Session, company_id: int, last_n_calls: int = 4) -> dict:
    basis, series = actuals(db, company_id)
    docs = db.scalars(select(FinancialDocument).where(
        FinancialDocument.company_id == company_id, FinancialDocument.doc_type == "concall_transcript",
        FinancialDocument.status == "guidance_extracted")
        .order_by(FinancialDocument.published_on.desc()).limit(last_n_calls)).all()
    by_doc = {d.id: d for d in docs}
    rows = db.scalars(select(ManagementGuidance).where(ManagementGuidance.source_document_id.in_(by_doc))
                      .order_by(ManagementGuidance.id)).all()
    ebit_ranges = frozenset((g.target_low, g.target_high) for g in rows
                            if g.metric == "ebitda_margin" and _is_ebit(g.statement))
    out = []
    for i, g in enumerate(rows, start=1):
        doc = by_doc[g.source_document_id]
        target = None
        if g.target_low is not None:
            unit = {"pct": "%", "cr": " cr", "pp": "pp"}.get(g.target_unit, "")
            target = (f"{g.target_low:g}{unit}" if g.target_high in (None, g.target_low)
                      else f"{g.target_low:g}-{g.target_high:g}{unit}")
            if g.target_high is None and re.search(r"double|over|above|at least|more than|upwards of|in excess",
                                                   g.statement, re.I):
                target = f"≥{g.target_low:g}{unit}"
        out.append({"id": i, "stated_in": g.stated_in_period, "quote": g.statement, "metric": g.metric,
                    "type": g.guidance_type, "target": target, "target_period": g.target_period,
                    "target_low": g.target_low, "target_high": g.target_high, "unit": g.target_unit,
                    "scope": g.scope, "segment": g.segment,
                    **measure(g, series, ebit_ranges),
                    "source": {"title": doc.title, "page": g.source_location, "url": doc.source_url}})
    # the same promise restated on a later call is one promise (reiterated), not two misses
    first: dict = {}
    for r in sorted(out, key=lambda r: (_q(r["stated_in"] or "") or (0, 0), r["id"])):
        if r["target"] is None:
            continue
        k = (r["metric"], r["target"], r["target_period"], r["scope"], r["segment"])
        if k not in first:
            first[k] = r
            continue
        r["same_as"] = first[k]["id"]
        again = first[k].setdefault("reiterated_in", [])
        if r["stated_in"] != first[k]["stated_in"] and r["stated_in"] not in again:
            again.append(r["stated_in"])
    counts = Counter(r["status"] for r in out if "same_as" not in r)
    return {"basis": basis, "calls": [{"period": d.period, "title": d.title, "url": d.source_url} for d in docs],
            "rows": out, "counts": dict(counts),
            "margin_definition": "operating profit / revenue (screener.in) where available, else FINN EBITDA"}


def guidance_narrative(db: Session, company_name: str, table: dict) -> dict | None:
    rows = [{k: r.get(k) for k in ("id", "stated_in", "quote", "metric", "target", "target_period", "scope",
                                   "segment", "status", "actual", "measured_over", "reason")} for r in table["rows"]]
    if not rows:
        return None
    res = generate(db, "guidance_narrative",
                   [{"text": f"Company: {company_name}\nRows:\n" + "\n".join(map(str, rows))}],
                   tier="strong", system=NARRATIVE_SYSTEM, schema=NARRATIVE_SCHEMA, thinking="low")
    out = {**res.data, "model": res.model}
    # The model may not overstate the evidence: a verdict on delivery needs at least one
    # guided period that has fully reported. Half a year "on track" is not "delivers".
    statuses = {r["status"] for r in table["rows"]}
    if not statuses & {"met", "missed", "exceeded"} and out["verdict"] in ("delivers", "over_promises"):
        out["verdict"] = "tracking" if statuses & {"on_track", "behind"} else "too_early"
        out["verdict_capped"] = True
    return out
