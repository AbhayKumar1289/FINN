"""Get any NSE company research-ready: discover documents, index them, extract guidance.
Idempotent; each step skips work already done, and LLM calls are cached."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest import nse_master
from app.ingest.screener import sync_company
from app.models import Company, FinancialDocument
from app.research.guidance import extract_guidance
from app.research.index import index_document

log = logging.getLogger(__name__)

TRANSCRIPTS = 5  # last four quarters, plus the call before them (its guidance covers that year)


def get_or_create_company(db: Session, symbol: str) -> Company | None:
    symbol = symbol.upper()
    company = db.scalar(select(Company).where(Company.nse_symbol == symbol))
    if company is not None:
        return company
    listing = nse_master.lookup(symbol)
    if listing is None:
        return None
    company = Company(nse_symbol=symbol, name=listing["legal_name"].removesuffix(" Limited"),
                      meta={"legal_name": listing["legal_name"], "isin": listing["isin"]})
    db.add(company)
    db.commit()
    return company


def prepare_company(db: Session, company: Company, transcripts: int = TRANSCRIPTS,
                    annual_report: bool = True) -> dict:
    out: dict = {"symbol": company.nse_symbol, "sync": sync_company(db, company), "indexed": [],
                 "guidance": [], "errors": []}
    docs = db.scalars(select(FinancialDocument).where(
        FinancialDocument.company_id == company.id, FinancialDocument.doc_type == "concall_transcript")
        .order_by(FinancialDocument.published_on.desc()).limit(transcripts)).all()
    if annual_report:
        ar = db.scalar(select(FinancialDocument).where(
            FinancialDocument.company_id == company.id, FinancialDocument.doc_type == "annual_report")
            .order_by(FinancialDocument.published_on.desc()).limit(1))
        docs = [*docs, ar] if ar else docs
    for doc in docs:
        try:
            if doc.status in ("discovered", "downloaded", "failed"):
                out["indexed"].append({"title": doc.title, "chunks": index_document(db, doc)})
            if doc.doc_type == "concall_transcript" and doc.status == "indexed":
                out["guidance"].append({"title": doc.title, "items": len(extract_guidance(db, doc))})
        except Exception as exc:
            db.rollback()
            log.exception("prepare failed on %s", doc.source_url)
            doc = db.get(FinancialDocument, doc.id)
            doc.status, doc.error = "failed", str(exc)[:300]
            db.commit()
            out["errors"].append({"title": doc.title, "error": str(exc)[:200]})
    return out
