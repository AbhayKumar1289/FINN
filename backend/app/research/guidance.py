"""Management guidance from concall transcripts.

The cheap model reads only the pages most likely to hold guidance (keyword-scored, usually a
third of the call) and copies statements verbatim. Every quote is then searched for in the
PDF's own text, and quotes that can't be found are dropped: an invented promise is worse
than a missed one."""
import re

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.extract.documents import fetch_pdf, page_texts, subset_pdf
from app.llm.client import generate, pdf_part
from app.models import FinancialDocument, ManagementGuidance

MAX_PAGES = 8
STRONG = re.compile(r"guid|outlook|target|aspir|expect|we aim|we see|going forward|next year|this year"
                    r"|full[- ]year|fy\s?'?\d{2}|double[- ]digit|range of|in the range", re.I)
WEAK = re.compile(r"margin|growth|capex|order inflow|order book|volume|revenue", re.I)

METRICS = ["revenue_growth", "ebitda_margin", "pat_growth", "order_inflow_growth", "order_book",
           "capex", "volume_growth", "other_margin", "working_capital", "other"]
NUM = {"type": "number", "nullable": True}
SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
    "quote": {"type": "string", "description": "verbatim sentence(s) from the transcript"},
    "speaker": {"type": "string", "nullable": True},
    "metric": {"type": "string", "enum": METRICS},
    "guidance_type": {"type": "string", "enum": ["explicit_numeric", "qualitative", "aspirational"]},
    "target_low": NUM, "target_high": NUM,
    "unit": {"type": "string", "enum": ["pct", "cr", "pp", "none"]},
    "target_period": {"type": "string", "nullable": True, "description": "e.g. FY27, Q3FY27, H2FY27"},
    "scope": {"type": "string", "enum": ["company", "segment"],
              "description": "whole company/group, or one segment/business/geography"},
    "segment": {"type": "string", "nullable": True, "description": "segment name when scope is segment"},
    "page": {"type": "integer", "description": "1-based page in the attached PDF"}},
    "required": ["quote", "metric", "guidance_type", "unit", "scope"]}}}, "required": ["items"]}

SYSTEM = ("You extract forward-looking guidance given by company management (not analysts' questions) "
          "from an Indian earnings-call transcript. Include only statements about the future: targets, "
          "ranges, expectations for growth, margins, order inflow, capex and similar. Copy the quote "
          "verbatim, one or two sentences. Numbers as stated: 'around 10%' -> low 10, high 10; "
          "'8 to 10%' -> 8 and 10; 'double-digit' -> low 10, high null. Fiscal years end in March: "
          "write periods as FY27, Q3FY27, H2FY27. Mark scope=segment when the target is for one "
          "segment or business (e.g. 'Projects & Manufacturing margin'), not the whole company. "
          "Skip pleasantries and historical facts.")


def guidance_pages(texts: list[str], limit: int = MAX_PAGES) -> list[int]:
    scored = [(len(STRONG.findall(t)) * 3 + len(WEAK.findall(t)), i) for i, t in enumerate(texts)]
    keep = [i for s, i in sorted(scored, reverse=True)[:limit] if s > 0]
    return sorted(keep)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def locate_quote(quote: str, texts: list[str]) -> int | None:
    """1-based page where the quote appears, matching any 6-word run of it; None if nowhere."""
    words = _norm(quote).split()
    if len(words) < 6:
        return None
    pages = [_norm(t) for t in texts]
    for start in range(0, len(words) - 5, 3):
        shingle = " ".join(words[start:start + 6])
        for i, p in enumerate(pages):
            if shingle in p:
                return i + 1
    return None


def normalise_period(p: str | None) -> str | None:
    if not p:
        return None
    m = re.search(r"\b(Q[1-4]|H[12])?\s*FY\s*'?(?:20)?(\d{2})\b", p.upper().replace("-", ""))
    return f"{m.group(1) or ''}FY{m.group(2)}" if m else None


def period_context(stated_in: str | None) -> str:
    if not stated_in:
        return ""
    fy = int(stated_in[-2:])
    q = stated_in[:2]
    current = fy + 1 if q == "Q4" else fy  # on the Q4 call, "this year" is the year starting now
    return (f"This call discusses {stated_in} results. 'This year' / 'current year' means FY{current}; "
            f"'next year' means FY{current + 1}.")


def extract_guidance(db: Session, doc: FinancialDocument) -> list[ManagementGuidance]:
    doc, data = fetch_pdf(db, doc.company_id, doc.source_url, doc.doc_type, doc.title, doc.period)
    texts = page_texts(data)
    pages = guidance_pages(texts)
    if not pages:
        return []
    res = generate(db, "guidance_extract",
                   [pdf_part(subset_pdf(data, pages)), {"text": period_context(doc.period)}],
                   tier="cheap", system=SYSTEM, schema=SCHEMA, thinking="low")
    db.execute(delete(ManagementGuidance).where(ManagementGuidance.source_document_id == doc.id))
    kept = []
    for item in res.data.get("items") or []:
        page = locate_quote(item.get("quote", ""), texts)
        if page is None:
            continue  # not verifiable in the source: drop it
        g = ManagementGuidance(
            company_id=doc.company_id, statement=item["quote"].strip(), guidance_type=item["guidance_type"],
            metric=item["metric"], target_low=item.get("target_low"), target_high=item.get("target_high"),
            target_unit=item.get("unit"), target_period=normalise_period(item.get("target_period")),
            stated_in_period=doc.period, source_document_id=doc.id, source_location=f"p.{page}",
            scope=item.get("scope") or "company", segment=item.get("segment"))
        db.add(g)
        kept.append(g)
    doc.status = "guidance_extracted"
    db.commit()
    return kept
