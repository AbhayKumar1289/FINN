"""Spend LLM tokens only where the brief asks for depth: results filings and senior/board
management changes. Everything else keeps its free rule-based summary."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.extract.people import extract_people
from app.extract.results import extract_results
from app.models import Announcement, PortfolioCompany

log = logging.getLogger(__name__)

ENRICHERS = {
    ("results", "filing"): ("results", extract_results),
    ("management_change", "senior"): ("people", extract_people),
    ("management_change", "board"): ("people", extract_people),
}
MAX_ATTEMPTS = 2
LOOKBACK_DAYS = 7


def _key(ann: Announcement) -> tuple:
    return ann.category, ((ann.extracted or {}).get("classification") or {}).get("subtype")


def needs_enrichment(ann: Announcement) -> bool:
    if _key(ann) not in ENRICHERS or not ann.document_url:
        return False
    state = (ann.extracted or {}).get("enrichment") or {}
    return state.get("status") != "ok" and state.get("attempts", 0) < MAX_ATTEMPTS


def enrich_announcement(db: Session, ann: Announcement) -> dict:
    field, fn = ENRICHERS[_key(ann)]
    state = dict((ann.extracted or {}).get("enrichment") or {})
    state["attempts"] = state.get("attempts", 0) + 1
    state["at"] = datetime.now(timezone.utc).isoformat()
    try:
        out = fn(db, ann)
        ann.extracted = {**(ann.extracted or {}), field: out, "enrichment": {**state, "status": "ok"}}
        if field == "results":
            ann.why_it_matters = out["verdict"]
        db.commit()
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
