import logging
import math
from datetime import date, datetime, time, timedelta, timezone

import pandas as pd
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Company, DailyPrice, IngestRun, PortfolioCompany

log = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))  # no DST, so a fixed offset is exact
SETTLE_AFTER = time(15, 45)  # NSE closes 15:30 IST; give the EOD bar a few minutes to settle


def yahoo_symbol(nse_symbol: str) -> str:
    return f"{nse_symbol}.NS"


def _frame_for(df: pd.DataFrame, ysym: str, n_symbols: int) -> pd.DataFrame | None:
    if isinstance(df.columns, pd.MultiIndex):
        if ysym not in df.columns.get_level_values(0):
            return None
        return df[ysym]
    return df if n_symbols == 1 else None


def is_settled(trading_date: date, now: datetime | None = None) -> bool:
    """During market hours Yahoo serves today's partial bar; storing it as end-of-day would
    fire false volume alerts (volume looks tiny) and stale price moves."""
    now_ist = (now or datetime.now(timezone.utc)).astimezone(IST)
    return trading_date < now_ist.date() or now_ist.time() >= SETTLE_AFTER


def _rows(company_id: int, frame: pd.DataFrame, now: datetime | None = None) -> list[dict]:
    rows = []
    for idx, r in frame.dropna(subset=["Close", "Volume"]).iterrows():
        vals = [r.get("Open"), r.get("High"), r.get("Low"), r.get("Close")]
        if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in vals):
            continue
        if not is_settled(pd.Timestamp(idx).date(), now):
            continue
        adj = r.get("Adj Close", r["Close"])
        rows.append({
            "company_id": company_id,
            "trading_date": pd.Timestamp(idx).date(),
            "open": float(r["Open"]), "high": float(r["High"]),
            "low": float(r["Low"]), "close": float(r["Close"]),
            "adj_close": float(adj if not pd.isna(adj) else r["Close"]),
            "volume": int(r["Volume"]),
        })
    return rows


def upsert_prices(db: Session, rows: list[dict]) -> int:
    if not rows:
        return 0
    for i in range(0, len(rows), 500):
        batch = rows[i:i + 500]
        stmt = insert(DailyPrice).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=["company_id", "trading_date"],
            set_={c: stmt.excluded[c] for c in ("open", "high", "low", "close", "adj_close", "volume")},
        )
        db.execute(stmt)
    db.commit()
    return len(rows)


def refresh_prices(db: Session, companies: list[Company] | None = None,
                   period: str | None = None) -> dict:
    if companies is None:
        companies = list(db.scalars(select(Company).join(PortfolioCompany)))
    run = IngestRun(source="prices")
    db.add(run)
    db.commit()

    by_symbol = {yahoo_symbol(c.nse_symbol): c for c in companies}
    detail = {"ok": [], "missing": [], "rows": 0}
    try:
        df = yf.download(list(by_symbol), period=period or settings.price_history_period,
                         interval="1d", auto_adjust=False, group_by="ticker",
                         progress=False, threads=True)
        for ysym, company in by_symbol.items():
            frame = _frame_for(df, ysym, len(by_symbol))
            rows = _rows(company.id, frame) if frame is not None else []
            if rows:
                detail["rows"] += upsert_prices(db, rows)
                detail["ok"].append(company.nse_symbol)
            else:
                detail["missing"].append(company.nse_symbol)
        run.status = "ok" if not detail["missing"] else ("partial" if detail["ok"] else "failed")
    except Exception as exc:  # network, rate limit, schema change
        log.exception("price refresh failed")
        run.status = "failed"
        detail["error"] = str(exc)
    run.detail = detail
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": run.status, **detail}


def validate_nse_symbol(symbol: str) -> bool:
    """Cheap existence check used when the user adds an unseen ticker."""
    try:
        hist = yf.Ticker(yahoo_symbol(symbol)).history(period="5d", auto_adjust=False)
        return not hist.empty
    except Exception:
        return False
