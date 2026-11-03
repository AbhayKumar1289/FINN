"""Spend LLM tokens only where depth pays: results filings, senior/board management changes,
material mid-priority filings (order wins, M&A, fund raises, ratings, legal, capex) and
earnings-call transcripts. Routine paperwork keeps its free rule-based summary."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.extract.brief import extract_brief, ingest_transcript
from app.extract.people import extract_people
from app.extract.results import extract_results
from app.models import Announcement, PortfolioCompany
from app.pipeline.process import process_announcements

log = logging.getLogger(__name__)

ENRICHERS = {
    ("results", "filing"): ("results", extract_results),
    ("management_change", "senior"): ("people", extract_people),
    ("management_change", "board"): ("people", extract_people),
    ("earnings_call", "transcript"): ("transcript", ingest_transcript),
    # (category, None) covers every subtype of the category
    ("press_release", "order_win"): ("brief", extract_brief),
    ("press_release", "regulatory_approval"): ("brief", extract_brief),
    ("m_and_a", None): ("brief", extract_brief),
    ("fund_raise", None): ("brief", extract_brief),
    ("credit_rating", None): ("brief", extract_brief),
    ("litigation", None): ("brief", extract_brief),
    ("capex", None): ("brief", extract_brief),
}
BRIEF_MIN_SCORE = 40  # a brief is for filings that reach a card, not the routine fold
MAX_ATTEMPTS = 2
LOOKBACK_DAYS = 7


def _key(ann: Announcement) -> tuple:
    return ann.category, ((ann.extracted or {}).get("classification") or {}).get("subtype")


def enricher_for(ann: Announcement) -> tuple | None:
    key = _key(ann)
    return ENRICHERS.get(key) or ENRICHERS.get((key[0], None))


def needs_enrichment(ann: Announcement) -> bool:
    found = enricher_for(ann)
    if found is None or not ann.document_url or not ann.document_url.lower().endswith(".pdf"):
        return False
    if found[0] == "brief" and (ann.priority_score or 0) < BRIEF_MIN_SCORE:
        return False
    state = (ann.extracted or {}).get("enrichment") or {}
    return state.get("status") != "ok" and state.get("attempts", 0) < MAX_ATTEMPTS


def enrich_announcement(db: Session, ann: Announcement) -> dict:
    field, fn = enricher_for(ann)
    state = dict((ann.extracted or {}).get("enrichment") or {})
    state["attempts"] = state.get("attempts", 0) + 1
    state["at"] = datetime.now(timezone.utc).isoformat()
    try:
        out = fn(db, ann)
        ann.extracted = {**(ann.extracted or {}), field: out, "enrichment": {**state, "status": "ok"}}
        if field == "results":
            ann.why_it_matters = out["verdict"]
        if field in ("brief", "transcript"):
            ann.extracted = {**ann.extracted, "headline": out.get("headline") or ann.extracted.get("headline")}
            ann.summary = out.get("summary") or ann.summary
            ann.why_it_matters = out.get("why") or ann.why_it_matters
            if out.get("materiality"):
                ann.extracted = {**ann.extracted, "materiality": out["materiality"]}
        db.commit()
        if field in ("brief", "results"):  # re-score: materiality, and the results explanation
            process_announcements(db, ids=[ann.id])
        return {"id": ann.id, "status": "ok"}
    except Exception as exc:
        db.rollback()
        log.exception("enrichment failed for announcement %s", ann.id)
        ann = db.get(Announcement, ann.id)
        ann.extracted = {**(ann.extracted or {}),
                         "enrichment": {**state, "status": "failed", "error": str(exc)[:500]}}
        db.commit()
        return {"id": ann.id, "status": "failed", "error": str(exc)[:200]}


def enrich_pending(db: Session, limit: int | None = None) -> list[dict]:
    if not settings.gemini_api_key:
        return []
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=LOOKBACK_DAYS)
    anns = db.scalars(select(Announcement)
                      .join(PortfolioCompany, PortfolioCompany.company_id == Announcement.company_id)
                      .where(Announcement.processing_status == "processed",
                             Announcement.published_at >= since)
                      .order_by(Announcement.priority_score.desc())).all()
    todo = [a for a in anns if needs_enrichment(a)][: limit or settings.max_enrich_per_cycle]
    return [enrich_announcement(db, a) for a in todo]
