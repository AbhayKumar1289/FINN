"""Mid-priority filings: say what actually happened instead of echoing the exchange's subject
line, and let code judge materiality.

* brief: the cheap model reads the first pages and returns a specific headline, a one-line
  summary and any rupee amount as printed. Code converts units and, for order wins, compares the
  value with trailing-twelve-month revenue: that ratio, not the word "order", decides priority.
* transcript: an earnings-call transcript filed on the exchange goes straight into Research
  (indexed, guidance extracted), so Push feeds Pull without anyone asking."""
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.extract.documents import fetch_pdf, page_texts, subset_pdf
from app.finance.calc import to_crore
from app.ingest.screener import call_period
from app.llm.client import generate, pdf_part
from app.models import Announcement, Company, FinancialDocument
from app.research.delivery import actuals
from app.research.guidance import extract_guidance
from app.research.index import index_document
from app.services.market import IST

MAX_PAGES = 3
NUM = {"type": "number", "nullable": True}
SCHEMA = {"type": "object", "properties": {
    "headline": {"type": "string", "description": "specific, at most 10 words, no company name"},
    "summary": {"type": "string", "description": "one or two plain sentences: what happened, with whom, how much"},
    "counterparty": {"type": "string", "nullable": True, "description": "customer, target, investor or agency"},
    "value_low": NUM, "value_high": NUM,
    "value_unit": {"type": "string", "enum": ["crore", "lakh", "million", "billion", "rupees",
                                              "usd_million", "usd_billion", "none"],
                   "description": "unit of the amount exactly as the filing states it (INR unless USD)"},
    "key_points": {"type": "array", "items": {"type": "string"}, "description": "at most 3 short facts"}},
    "required": ["headline", "summary", "value_unit"]}

SYSTEM = ("You summarise Indian stock-exchange filings for a busy investor. Read the attached filing and "
          "state what happened specifically: what, with whom, how much, by when. Copy amounts exactly as "
          "written with their unit; when a range is given (e.g. 'significant' orders worth ₹1,000-2,500 "
          "crore) give both ends. Never convert units or compute anything. No boilerplate about "
          "regulations or the exchange.")


def ttm_revenue(db: Session, company_id: int) -> float | None:
    """Sum of the latest four reported quarters, ₹ crore."""
    _, series = actuals(db, company_id)
    quarters = sorted((k for k, v in series.items() if v.get("revenue") is not None), reverse=True)[:4]
    if len(quarters) < 4:
        return None
    return sum(series[q]["revenue"] for q in quarters)


def materiality(db: Session, company_id: int, low_cr: float | None, high_cr: float | None) -> dict | None:
    if low_cr is None and high_cr is None:
        return None
    ttm = ttm_revenue(db, company_id)
    if not ttm:
        return None
    # judge on the conservative end of a range
    value = low_cr if low_cr is not None else high_cr
    return {"value_cr": value, "ttm_revenue_cr": round(ttm), "pct_of_revenue": round(value / ttm * 100, 2)}


def materiality_why(pct: float, company: str) -> str:
    if pct >= 5:
        return f"Large: worth about {pct:.0f}% of a year's revenue, enough to move {company}'s growth outlook."
    if pct >= 1:
        return f"Worth about {pct:.1f}% of a year's revenue: a solid win, but routine at {company}'s scale."
    return f"Small next to the business (under 1% of annual revenue); unlikely to change the picture."


def extract_brief(db: Session, ann: Announcement) -> dict:
    company = db.get(Company, ann.company_id)
    _, data = fetch_pdf(db, company.id, ann.document_url, "announcement", ann.summary or ann.title)
    pages = list(range(min(len(page_texts(data)), MAX_PAGES)))
    res = generate(db, "filing_brief", [pdf_part(subset_pdf(data, pages)), {"text": f"Company: {company.name}."}],
                   tier="cheap", system=SYSTEM, schema=SCHEMA, thinking="low")
    d = res.data
    unit = d.get("value_unit") or "none"
    low = high = None
    if unit in ("crore", "lakh", "million", "billion", "rupees"):
        low = None if d.get("value_low") is None else round(to_crore(d["value_low"], unit), 2)
        high = None if d.get("value_high") is None else round(to_crore(d["value_high"], unit), 2)
    out = {"headline": d.get("headline"), "summary": d.get("summary"), "counterparty": d.get("counterparty"),
           "key_points": (d.get("key_points") or [])[:3], "value_low_cr": low, "value_high_cr": high,
           "value_note": f"{d.get('value_low')} {unit.replace('_', ' ')}" if unit.startswith("usd") else None}
    mat = materiality(db, company.id, low, high)
    if mat:
        out["materiality"] = mat
        out["why"] = materiality_why(mat["pct_of_revenue"], company.name)
    return out


def ingest_transcript(db: Session, ann: Announcement) -> dict:
    filed = ann.published_at.replace(tzinfo=timezone.utc).astimezone(IST).date()
    period = call_period(filed)
    doc = db.scalar(select(FinancialDocument).where(FinancialDocument.company_id == ann.company_id,
                                                    FinancialDocument.source_url == ann.document_url))
    if doc is None:
        doc = FinancialDocument(company_id=ann.company_id, doc_type="concall_transcript",
                                title=f"Concall transcript, {filed:%b %Y}", source_url=ann.document_url,
                                period=period, published_on=filed, status="discovered")
        db.add(doc)
        db.commit()
    if doc.status in ("discovered", "downloaded", "failed"):
        index_document(db, doc)
    items = extract_guidance(db, doc) if doc.status == "indexed" else []
    n = len(items)
    return {"period": period, "guidance_count": n,
            "headline": f"{period} call transcript is out",
            "why": "Management's own words on the outlook: see what they promised and whether past promises held.",
            "summary": (f"FINN read it and extracted {n} guidance statement{'s' if n != 1 else ''}; "
                        "they now feed this company's promised-vs-delivered view.") if n else
                       "FINN read it and added it to this company's research; no new numeric guidance."}
