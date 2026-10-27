"""Threshold alerts. Each alert has a dedupe key, so re-running evaluation is always safe:
one alert per stock per session per rule, and one per company per category per session."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.finance.calc import crosses
from app.models import Alert, AlertRule, Announcement, Company, PortfolioCompany
from app.services.market import IST, price_rows, signals_for


def rule_map(db: Session) -> dict[str, AlertRule]:
    return {r.rule_type: r for r in db.scalars(select(AlertRule))}


def _create(db: Session, **values) -> bool:
    stmt = insert(Alert).values(**values).on_conflict_do_nothing(index_elements=["dedupe_key"])
    return db.execute(stmt).rowcount > 0


def _portfolio(db: Session) -> list[Company]:
    return list(db.scalars(select(Company).join(PortfolioCompany)))


def evaluate_market(db: Session, sessions: int = 1) -> int:
    """Check the last `sessions` EOD bars of every portfolio stock."""
    rules = rule_map(db)
    price_rule, vol_rule = rules.get("price_move"), rules.get("volume_spike")
    lookback = int((vol_rule.config or {}).get("lookback", settings.volume_lookback_days)) if vol_rule \
        else settings.volume_lookback_days
    created = 0
    for company in _portfolio(db):
        rows = price_rows(db, company.id, limit=lookback + sessions + 1)
        for i in range(max(1, len(rows) - sessions), len(rows)):
            window = rows[:i + 1]
            bar = window[-1]
            change, rvol = signals_for(window, lookback)
            day = bar.trading_date
            if price_rule and price_rule.enabled and change.value is not None \
                    and crosses(abs(change.value), price_rule.threshold):
                created += _create(
                    db, company_id=company.id, rule_id=price_rule.id,
                    dedupe_key=f"price_move:{company.nse_symbol}:{day}",
                    message=f"{company.nse_symbol} {change.value:+.1f}% on {day:%d %b} "
                            f"(your threshold ±{price_rule.threshold:g}%)",
                    observed_value=round(change.value, 2), threshold_value=price_rule.threshold,
                    as_of=day, source_reference={"type": "eod", "trading_date": day.isoformat()})
            if vol_rule and vol_rule.enabled and crosses(rvol, vol_rule.threshold):
                created += _create(
                    db, company_id=company.id, rule_id=vol_rule.id,
                    dedupe_key=f"volume_spike:{company.nse_symbol}:{day}",
                    message=f"{company.nse_symbol} volume {rvol:.1f}x its {lookback}-day average "
                            f"on {day:%d %b} (your threshold {vol_rule.threshold:g}x)",
                    observed_value=round(rvol, 2), threshold_value=vol_rule.threshold,
                    as_of=day, source_reference={"type": "eod", "trading_date": day.isoformat()})
    db.commit()
    return created


def matches_category(rule_categories: list[str], category: str | None, subtype: str | None) -> bool:
    return category in rule_categories or f"{category}:{subtype}" in rule_categories


def evaluate_announcements(db: Session, since: datetime) -> int:
    rule = rule_map(db).get("announcement_category")
    if rule is None or not rule.enabled:
        return 0
    categories = (rule.config or {}).get("categories", [])
    min_score = float((rule.config or {}).get("min_score", 40))
    anns = db.scalars(select(Announcement).join(PortfolioCompany,
                                                PortfolioCompany.company_id == Announcement.company_id)
                      .where(Announcement.processing_status == "processed",
                             Announcement.published_at >= since)
                      .order_by(Announcement.priority_score.desc())).all()
    created = 0
    for ann in anns:
        subtype = ((ann.extracted or {}).get("classification") or {}).get("subtype")
        if not matches_category(categories, ann.category, subtype) or (ann.priority_score or 0) < min_score:
            continue
        company = db.get(Company, ann.company_id)
        # one event per company, category and filing day (IST): a results filing at 15:27 and
        # its press release at 15:39 are the same news, even though they straddle the close
        filed_on = ann.published_at.replace(tzinfo=timezone.utc).astimezone(IST).date()
        extracted = ann.extracted or {}
        headline = extracted.get("headline") or ann.category
        detail = (extracted.get("results") or {}).get("line") or (extracted.get("people") or {}).get("line")
        created += _create(
            db, company_id=ann.company_id, rule_id=rule.id,
            dedupe_key=f"ann:{company.nse_symbol}:{ann.category}:{filed_on}",
            message=f"{company.nse_symbol}: {headline}" + (f" — {detail}" if detail else ""),
            observed_value=ann.priority_score, threshold_value=min_score,
            as_of=ann.published_at.date(),
            source_reference={"type": "announcement", "announcement_id": ann.id,
                              "url": ann.document_url or ann.original_url})
    db.commit()
    return created
