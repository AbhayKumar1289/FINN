from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select

from app.alerts.engine import evaluate_announcements, evaluate_market
from app.ingest.announcements import norm_name, parse_feed, refresh_announcements
from app.ingest.prices import is_settled
from app.jobs import prices_due
from app.models import Alert, AlertRule, Announcement, Company, DailyPrice, IngestRun
from app.pipeline.process import process_announcements
from app.services.digest import build_digest
from app.services.market import market_reaction, reaction_session

IST = timezone(timedelta(hours=5, minutes=30))
DAY_START = datetime(2026, 10, 26, 18, 30)  # 27 Oct 00:00 IST, as naive UTC
DAY_END = datetime(2026, 10, 27, 18, 30)


def ingest(db, feed_bytes):
    result = refresh_announcements(db, feed_bytes)
    process_announcements(db, ids=result["new_ids"])
    return result


def company(db, symbol):
    return db.scalar(select(Company).where(Company.nse_symbol == symbol))


def count(db, symbol):
    return db.scalar(select(func.count(Announcement.id)).where(Announcement.company_id == company(db, symbol).id))


# ---------- ingestion ----------
def test_name_normalisation():
    assert norm_name("Dr. Reddy's Laboratories Limited") == norm_name("DR. REDDY'S LABORATORIES LTD")
    assert norm_name("Mahindra & Mahindra Limited") == "mahindra and mahindra"
    assert norm_name("Mahindra & Mahindra Financial Services Limited") != "mahindra and mahindra"


def test_feed_parses_ist_to_utc(feed_bytes):
    items = parse_feed(feed_bytes)
    assert items and all(i.published_at.tzinfo is None for i in items)
    lt = next(i for i in items if i.company_name == "Larsen & Toubro Limited" and "financial results" in i.text)
    assert lt.published_at == datetime(2026, 10, 27, 11, 43, 9)  # 17:13:09 IST


def test_ingest_matches_exactly_and_dedupes(db, feed_bytes):
    result = ingest(db, feed_bytes)
    assert result["status"] == "ok" and result["new"] > 0
    assert count(db, "M&M") == 0      # M&M Financial Services filed; that's a different company
    assert count(db, "NTPC") == 1     # the exchange sent the same record-date item four times
    assert count(db, "LT") >= 3
    again = refresh_announcements(db, feed_bytes)
    assert again["new"] == 0


def test_failed_fetch_is_recorded(db):
    result = refresh_announcements(db, b"<rss><channel><item>")  # truncated body
    assert result["status"] == "failed"
    run = db.scalar(select(IngestRun).where(IngestRun.source == "announcements"))
    assert run.status == "failed" and "error" in run.detail


# ---------- digest ----------
def test_digest_ranks_groups_and_collapses(db, feed_bytes):
    ingest(db, feed_bytes)
    d = build_digest(db, DAY_START, DAY_END)
    cards = d["cards"]
    assert cards[0]["priority"] == "high"
    assert [c["score"] for c in cards] == sorted((c["score"] for c in cards), reverse=True)
    maruti = next(c for c in cards if c["company"]["symbol"] == "MARUTI" and c["category"] == "results")
    assert maruti["subtype"] == "filing" and len(maruti["related"]) == 2  # press release + deck
    hdfc = next(c for c in cards if c["company"]["symbol"] == "HDFCBANK")
    assert hdfc["headline"] == "MD & CEO change"
    assert all(c["priority"] != "low" for c in cards)
    labels = {l for r in d["routine"]["companies"] for l in r["labels"]}
    assert "ESOP allotment" in labels
    assert d["routine"]["line"].endswith("companies")


def test_digest_window_is_respected(db, feed_bytes):
    ingest(db, feed_bytes)
    empty = build_digest(db, DAY_START - timedelta(days=2), DAY_START)
    assert empty["counts"]["filings"] == 0 and empty["cards"] == [] and empty["routine"]["line"] is None
    evening = build_digest(db, datetime(2026, 10, 27, 10, 0), DAY_END)  # after 15:30 IST
    assert all(c["published_at"] >= "2026-10-27T10:00" for c in evening["cards"])


# ---------- market reaction ----------
def add_prices(db, symbol, closes, volumes, start=date(2026, 9, 1)):
    cid = company(db, symbol).id
    for i, (c, v) in enumerate(zip(closes, volumes)):
        db.add(DailyPrice(company_id=cid, trading_date=start + timedelta(days=i), open=c, high=c,
                          low=c, close=c, adj_close=c, volume=v))
    db.commit()


def test_reaction_session_respects_close():
    assert reaction_session(datetime(2026, 10, 27, 9, 57)) == date(2026, 10, 27)   # 15:27 IST
    assert reaction_session(datetime(2026, 10, 27, 10, 9)) == date(2026, 10, 28)   # 15:39 IST


def test_reaction_pending_until_next_bar(db):
    add_prices(db, "INFY", [100] * 21, [1000] * 21)  # last bar 21 Sep
    after_close = datetime(2026, 9, 21, 11, 0)        # 16:30 IST
    assert market_reaction(db, company(db, "INFY").id, after_close)["status"] == "pending"
    add_prices(db, "INFY", [106], [3000], start=date(2026, 9, 22))
    r = market_reaction(db, company(db, "INFY").id, after_close)
    assert r["status"] == "ok" and r["change_pct"] == 6.0 and r["relative_volume"] == 3.0


# ---------- alerts ----------
def test_market_alerts_fire_once_and_respect_boundary(db):
    add_prices(db, "TCS", [100] * 20 + [94], [1000] * 20 + [2000])  # -6%, exactly 2.0x
    assert evaluate_market(db) == 2
    assert evaluate_market(db) == 0  # idempotent
    msgs = sorted(a.message for a in db.scalars(select(Alert)))
    assert msgs[0].startswith("TCS -6.0%") and "2.0x" in msgs[1]


def test_raising_threshold_silences_alert(db):
    rule = db.scalar(select(AlertRule).where(AlertRule.rule_type == "price_move"))
    rule.threshold = 7.0
    db.commit()
    add_prices(db, "TCS", [100] * 20 + [94], [1000] * 21)
    assert evaluate_market(db) == 0


def test_announcement_alerts_one_per_event(db, feed_bytes):
    ingest(db, feed_bytes)
    created = evaluate_announcements(db, since=DAY_START)
    keys = [a.dedupe_key for a in db.scalars(select(Alert))]
    assert created == len(keys) and len(keys) == len(set(keys))
    assert sum(k.startswith("ann:MARUTI:results") for k in keys) == 1  # filing + PR + deck = one alert
    assert not any("esop" in k or ":unclassified:" in k for k in keys)
    assert evaluate_announcements(db, since=DAY_START) == 0


# ---------- scheduling ----------
def test_live_bar_is_not_end_of_day():
    today = date(2026, 10, 27)
    assert not is_settled(today, datetime(2026, 10, 27, 11, 0, tzinfo=IST))
    assert is_settled(today, datetime(2026, 10, 27, 16, 0, tzinfo=IST))
    assert is_settled(date(2026, 10, 26), datetime(2026, 10, 27, 11, 0, tzinfo=IST))


def test_prices_due_once_per_day_after_close(db):
    evening = datetime(2026, 10, 27, 17, 0, tzinfo=IST)
    assert not prices_due(db, datetime(2026, 10, 27, 12, 0, tzinfo=IST))
    assert prices_due(db, evening)
    db.add(IngestRun(source="prices", status="ok",
                     finished_at=datetime(2026, 10, 27, 11, 0)))  # 16:30 IST
    db.commit()
    assert not prices_due(db, evening)
    assert prices_due(db, datetime(2026, 10, 28, 17, 0, tzinfo=IST))
