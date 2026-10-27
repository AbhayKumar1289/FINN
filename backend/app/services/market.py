from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.finance.calc import daily_price_change, relative_volume
from app.models import DailyPrice

IST = timezone(timedelta(hours=5, minutes=30))
MARKET_CLOSE = time(15, 30)
MAX_REACTION_GAP_DAYS = 5  # weekend + holiday; beyond that a later bar isn't "the reaction"


def price_rows(db: Session, company_id: int, limit: int = 260,
               until: date | None = None) -> list[DailyPrice]:
    q = select(DailyPrice).where(DailyPrice.company_id == company_id)
    if until is not None:
        q = q.where(DailyPrice.trading_date <= until)
    rows = db.scalars(q.order_by(DailyPrice.trading_date.desc()).limit(limit)).all()
    return list(reversed(rows))


def signals_for(rows: list[DailyPrice], lookback: int) -> tuple:
    change = daily_price_change([r.adj_close for r in rows])
    rvol = relative_volume([r.volume for r in rows], lookback)
    return change, rvol


def market_signals(db: Session, company_id: int, lookback: int | None = None) -> dict:
    lookback = lookback or settings.volume_lookback_days
    rows = price_rows(db, company_id, limit=lookback + 5)
    if not rows:
        return {"available": False, "reason": "no price data ingested"}
    last = rows[-1]
    change, rvol = signals_for(rows, lookback)
    return {
        "available": True,
        "as_of": last.trading_date.isoformat(),
        "stale_days": (date.today() - last.trading_date).days,
        "close": last.close,
        "day_change_pct": change.as_dict(),
        "volume": last.volume,
        "relative_volume": None if rvol is None else round(rvol, 2),
        "volume_lookback": lookback,
        "data_type": "end_of_day",
    }


def reaction_session(published_at_utc: datetime) -> date:
    """First session that could price in a filing: same day if filed before the close."""
    local = published_at_utc.replace(tzinfo=timezone.utc).astimezone(IST)
    return local.date() + timedelta(days=0 if local.time() < MARKET_CLOSE else 1)


def market_reaction(db: Session, company_id: int, published_at_utc: datetime,
                    lookback: int | None = None) -> dict:
    lookback = lookback or settings.volume_lookback_days
    start = reaction_session(published_at_utc)
    bar = db.scalar(select(DailyPrice).where(DailyPrice.company_id == company_id,
                                             DailyPrice.trading_date >= start)
                    .order_by(DailyPrice.trading_date).limit(1))
    if bar is None:
        return {"status": "pending", "from_session": start.isoformat()}
    if (bar.trading_date - start).days > MAX_REACTION_GAP_DAYS:
        return {"status": "unavailable"}
    rows = price_rows(db, company_id, limit=lookback + 1, until=bar.trading_date)
    change, rvol = signals_for(rows, lookback)
    return {"status": "ok", "session": bar.trading_date.isoformat(),
            "change_pct": None if change.value is None else round(change.value, 2),
            "relative_volume": None if rvol is None else round(rvol, 2)}
