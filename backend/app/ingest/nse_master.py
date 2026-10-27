"""NSE equity master list (official archive CSV): symbol -> legal name, ISIN.

Announcements are keyed by legal name, so this is what lets FINN follow any NSE ticker,
not just the seeded portfolio."""
import csv
import io
import logging
import time

import httpx

from app.config import settings

log = logging.getLogger(__name__)

EQUITY_LIST_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
_TTL_SECONDS = 24 * 3600
_cache: dict = {"at": 0.0, "rows": {}}


def fetch_equity_list() -> dict[str, dict]:
    r = httpx.get(EQUITY_LIST_URL, headers={"User-Agent": settings.nse_user_agent},
                  timeout=settings.http_timeout)
    r.raise_for_status()
    out = {}
    for row in csv.DictReader(io.StringIO(r.text)):
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        out[row["SYMBOL"]] = {"legal_name": row["NAME OF COMPANY"], "isin": row["ISIN NUMBER"],
                              "series": row["SERIES"]}
    return out


def _rows() -> dict[str, dict]:
    if time.time() - _cache["at"] > _TTL_SECONDS:
        try:
            _cache["rows"] = fetch_equity_list()
            _cache["at"] = time.time()
        except Exception:
            log.exception("could not fetch NSE equity list")
    return _cache["rows"]


def lookup(symbol: str) -> dict | None:
    """Master-list entry for a symbol, or None if unknown or NSE is unreachable."""
    return _rows().get(symbol.upper())


def search(q: str, limit: int = 8) -> list[dict]:
    """Symbol prefix matches first, then name matches: 'tit' -> TITAN, then '...Titagarh...'."""
    q = q.strip().upper()
    if not q:
        return []
    rows = _rows()
    prefix = [s for s in rows if s.startswith(q)]
    named = [s for s, r in rows.items() if q in r["legal_name"].upper() and s not in prefix]
    hits = sorted(prefix, key=len) + sorted(named)
    return [{"symbol": s, "name": rows[s]["legal_name"].removesuffix(" Limited")} for s in hits[:limit]]
