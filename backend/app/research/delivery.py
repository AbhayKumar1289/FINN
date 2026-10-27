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


def measure(g: ManagementGuidance, series: dict) -> dict:
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
    if g.metric == "ebitda_margin":
        m = _margin_metric(series)
        actual = margin(_sum(series, reported, m), _sum(series, reported, "revenue"))
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
            "partial": partial}


def guidance_table(db: Session, company_id: int, last_n_calls: int = 4) -> dict:
    basis, series = actuals(db, company_id)
    docs = db.scalars(select(FinancialDocument).where(
        FinancialDocument.company_id == company_id, FinancialDocument.doc_type == "concall_transcript",
        FinancialDocument.status == "guidance_extracted")
        .order_by(FinancialDocument.published_on.desc()).limit(last_n_calls)).all()
    by_doc = {d.id: d for d in docs}
    rows = db.scalars(select(ManagementGuidance).where(ManagementGuidance.source_document_id.in_(by_doc))
                      .order_by(ManagementGuidance.id)).all()
    out = []
    for i, g in enumerate(rows, start=1):
        doc = by_doc[g.source_document_id]
        target = None
        if g.target_low is not None:
            unit = {"pct": "%", "cr": " cr", "pp": "pp"}.get(g.target_unit, "")
            target = (f"{g.target_low:g}{unit}" if g.target_high in (None, g.target_low)
                      else f"{g.target_low:g}-{g.target_high:g}{unit}")
            if g.target_high is None and "double" in g.statement.lower():
                target = f"≥{g.target_low:g}{unit}"
        out.append({"id": i, "stated_in": g.stated_in_period, "quote": g.statement, "metric": g.metric,
                    "type": g.guidance_type, "target": target, "target_period": g.target_period,
                    "scope": g.scope, "segment": g.segment,
                    **measure(g, series),
                    "source": {"title": doc.title, "page": g.source_location, "url": doc.source_url}})
    counts = Counter(r["status"] for r in out)
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
    return {**res.data, "model": res.model}
