"""CLI:
  python -m app.jobs refresh-prices
  python -m app.jobs refresh-announcements
  python -m app.jobs ingest-file <feed.xml>      replay a saved NSE RSS file
  python -m app.jobs evaluate-alerts [sessions]
  python -m app.jobs enrich [limit]              LLM results numbers + appointee bios
  python -m app.jobs research <SYMBOL> [--no-ar]   index docs, guidance vs delivered
  python -m app.jobs cycle                       what the scheduler runs every POLL_MINUTES
  python -m app.jobs digest [hours]
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.engine import evaluate_announcements, evaluate_market
from app.db import Base, SessionLocal, add_missing_columns, engine
from app.extract.enrich import enrich_pending
from app.llm.usage import llm_usage
from app.ingest.announcements import refresh_announcements
from app.ingest.prices import IST, SETTLE_AFTER, refresh_prices
from app.models import IngestRun
from app.pipeline.process import process_announcements
from app.research.index import ensure_fts
from app.research.prepare import get_or_create_company, prepare_company
from app.research.delivery import guidance_narrative, guidance_table
from app.seed import seed
from app.services.digest import build_digest

RESCORE_DAYS = 5


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def prices_due(db: Session, now: datetime | None = None) -> bool:
    """Once per trading day, after the close has settled."""
    now_ist = (now or datetime.now(timezone.utc)).astimezone(IST)
    if now_ist.time() < SETTLE_AFTER:
        return False
    last = db.scalar(select(IngestRun).where(IngestRun.source == "prices",
                                             IngestRun.status.in_(("ok", "partial")))
                     .order_by(IngestRun.started_at.desc()).limit(1))
    if last is None or last.finished_at is None:
        return True
    last_ist = last.finished_at.replace(tzinfo=timezone.utc).astimezone(IST)
    return not (last_ist.date() == now_ist.date() and last_ist.time() >= SETTLE_AFTER)


def ingest_and_process(db: Session, content: bytes | None = None, enrich: bool = True) -> dict:
    ann = refresh_announcements(db, content)
    processed = process_announcements(db, ids=ann["new_ids"])
    # enrich before alerting, so a results alert can carry the numbers
    enriched = enrich_pending(db) if enrich else []
    alerts = evaluate_announcements(db, since=utcnow_naive() - timedelta(days=1))
    return {**{k: v for k, v in ann.items() if k != "new_ids"},
            "processed": processed, "enriched": enriched, "announcement_alerts": alerts}


def run_cycle(db: Session, force_prices: bool = False) -> dict:
    out = {"announcements": ingest_and_process(db)}
    if force_prices or prices_due(db):
        p = refresh_prices(db)
        out["prices"] = {"status": p["status"], "ok": len(p["ok"]), "missing": p["missing"]}
        # yesterday's after-hours filings get their market reaction now
        out["rescored"] = process_announcements(db, since=utcnow_naive() - timedelta(days=RESCORE_DAYS))
        out["market_alerts"] = evaluate_market(db)
        out["announcement_alerts"] = evaluate_announcements(db, since=utcnow_naive() - timedelta(days=1))
    return out


def main(argv: list[str]) -> None:
    cmd = argv[0] if argv else "cycle"
    Base.metadata.create_all(engine)
    add_missing_columns()
    ensure_fts(engine)
    with SessionLocal() as db:
        seed(db)
        if cmd == "refresh-prices":
            result = refresh_prices(db)
        elif cmd == "refresh-announcements":
            result = ingest_and_process(db)
        elif cmd == "ingest-file":
            result = ingest_and_process(db, Path(argv[1]).read_bytes())
        elif cmd == "evaluate-alerts":
            sessions = int(argv[1]) if len(argv) > 1 else 1
            result = {"market_alerts": evaluate_market(db, sessions=sessions),
                      "announcement_alerts": evaluate_announcements(
                          db, since=utcnow_naive() - timedelta(days=sessions + 1))}
        elif cmd == "enrich":
            result = {"enriched": enrich_pending(db, limit=int(argv[1]) if len(argv) > 1 else None),
                      "llm_usage": llm_usage(db)}
        elif cmd == "research":
            company = get_or_create_company(db, argv[1])
            if company is None:
                raise SystemExit(f"{argv[1]} is not a listed NSE symbol")
            prep = prepare_company(db, company, annual_report="--no-ar" not in argv)
            table = guidance_table(db, company.id)
            result = {"prepare": prep, "guidance": table,
                      "narrative": guidance_narrative(db, company.name, table)}
        elif cmd == "cycle":
            result = run_cycle(db, force_prices="--prices" in argv)
        elif cmd == "digest":
            hours = float(argv[1]) if len(argv) > 1 else 24
            end = utcnow_naive()
            result = build_digest(db, end - timedelta(hours=hours), end)
        else:
            raise SystemExit(f"unknown command {cmd}\n{__doc__}")
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
