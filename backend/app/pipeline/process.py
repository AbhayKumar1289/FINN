"""Turns stored announcements into triaged items. Classification runs once per filing;
scoring re-runs, because the market's reaction arrives a session later."""
import logging
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import AlertRule, Announcement
from app.pipeline.classify import Classification, classify
from app.pipeline.present import clean_summary, headline, why_it_matters
from app.pipeline.priority import bucket, score_announcement
from app.services.market import market_reaction

log = logging.getLogger(__name__)

PIPELINE_VERSION = "rules-1"


def thresholds(db: Session) -> tuple[float, float]:
    rules = {r.rule_type: r for r in db.scalars(select(AlertRule))}
    price = rules.get("price_move")
    vol = rules.get("volume_spike")
    return (price.threshold if price and price.threshold else 5.0,
            vol.threshold if vol and vol.threshold else 2.0)


def _classification(ann: Announcement) -> Classification:
    c = (ann.extracted or {}).get("classification") or {}
    return Classification(ann.category or "unclassified", c.get("subtype"), c.get("rule", ""),
                          c.get("details") or {})


def process_announcements(db: Session, ids: list[int] | None = None,
                          since: datetime | None = None) -> int:
    """Classify new filings; (re)score new ones plus any selected by `ids` / `since`."""
    conds = [Announcement.processing_status.in_(("new", "error"))]
    if ids:
        conds.append(Announcement.id.in_(ids))
    if since is not None:
        conds.append(Announcement.published_at >= since)
    price_t, vol_t = thresholds(db)
    n = 0
    for ann in db.scalars(select(Announcement).where(or_(*conds))).all():
        try:
            text = ann.raw_text or ann.title
            if ann.processing_status != "processed":
                cls = classify(ann.exchange_category, text)
                ann.category = cls.category
                ann.summary = clean_summary(text)
                ann.why_it_matters = why_it_matters(cls)
                ann.extracted = {**(ann.extracted or {}),
                                 "classification": {"subtype": cls.subtype, "rule": cls.rule,
                                                    "details": cls.details},
                                 "headline": headline(cls, text)}
            else:
                cls = _classification(ann)
            reaction = market_reaction(db, ann.company_id, ann.published_at)
            score, reasons = score_announcement(cls, reaction, price_t, vol_t)
            ann.extracted = {**(ann.extracted or {}), "reaction": reaction}
            ann.priority_score = score
            ann.priority = bucket(score)
            ann.priority_reasons = reasons
            ann.processing_status = "processed"
            ann.processing_error = None
            ann.pipeline_version = PIPELINE_VERSION
        except Exception as exc:
            log.exception("processing announcement %s failed", ann.id)
            ann.processing_status = "error"
            ann.processing_error = str(exc)
        n += 1
    db.commit()
    return n
