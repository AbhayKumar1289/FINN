import asyncio
import logging
import re
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.alerts.engine import evaluate_announcements, evaluate_market
from app.config import settings
from app.db import Base, SessionLocal, add_missing_columns, engine, get_db
from app.ingest import nse_master
from app.ingest.prices import refresh_prices, validate_nse_symbol
from app.jobs import ingest_and_process, run_cycle, utcnow_naive
from app.extract.enrich import enrich_pending
from app.llm.usage import llm_usage
from app.models import (Alert, AlertRule, Announcement, Company, CompanyStatements, FinancialDocument,
                        FinancialMetric, IngestRun, PortfolioCompany)
from app.pipeline.classify import CATEGORIES
from app.research.delivery import actuals, guidance_narrative, guidance_table
from app.research.fundamentals import analyse, inr
from app.research.perspective import bull_bear, business_snapshot
from app.research.index import ensure_fts
from app.research.prepare import get_or_create_company, prepare_company
from app.research.qa import ask
from app.seed import seed
from app.services.digest import announcement_out, build_digest, iso_utc
from app.services.market import IST, market_signals, price_rows, reaction_session

log = logging.getLogger(__name__)
SYMBOL_RE = re.compile(r"^[A-Z0-9&\-]{1,20}$")
MAX_WINDOW_HOURS = 24 * 30


def _run_cycle_once() -> dict:
    with SessionLocal() as db:
        return run_cycle(db)


async def _scheduler() -> None:
    while True:
        try:
            log.info("cycle: %s", await asyncio.to_thread(_run_cycle_once))
        except Exception:
            log.exception("scheduled cycle failed")
        await asyncio.sleep(settings.poll_minutes * 60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    add_missing_columns()
    ensure_fts(engine)
    with SessionLocal() as db:
        seed(db)
    task = asyncio.create_task(_scheduler()) if settings.enable_scheduler else None
    yield
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="FINN API", version="0.4.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list,
                   allow_origin_regex=settings.cors_origin_regex or None,
                   allow_methods=["*"], allow_headers=["*"])


def get_company(db: Session, symbol: str) -> Company:
    symbol = symbol.upper()
    if not SYMBOL_RE.match(symbol):
        raise HTTPException(400, "Invalid ticker format")
    company = db.scalar(select(Company).where(Company.nse_symbol == symbol))
    if company is None:
        raise HTTPException(404, f"{symbol} is not in FINN's company list")
    return company


def company_out(c: Company, db: Session) -> dict:
    return {"symbol": c.nse_symbol, "bse_code": c.bse_code, "name": c.name, "sector": c.sector,
            "is_financial": c.is_financial, "market": market_signals(db, c.id)}


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    last = {}
    for source in ("prices", "announcements", "documents"):
        run = db.scalar(select(IngestRun).where(IngestRun.source == source)
                        .order_by(IngestRun.started_at.desc()).limit(1))
        last[source] = None if run is None else {
            "status": run.status, "finished_at": iso_utc(run.finished_at), "detail": run.detail}
    return {"api": "ok", "companies": db.scalar(select(func.count(Company.id))),
            "scheduler": settings.enable_scheduler, "ingest": last}


# ---------- portfolio ----------
@app.get("/api/portfolio")
def list_portfolio(spark_days: int = Query(30, ge=0, le=120), db: Session = Depends(get_db)):
    companies = db.scalars(select(Company).join(PortfolioCompany).order_by(Company.name)).all()
    out = []
    for c in companies:
        row = company_out(c, db)
        if spark_days:
            row["spark"] = [round(r.adj_close, 2) for r in price_rows(db, c.id, limit=spark_days)]
        latest = db.scalar(select(Announcement).where(Announcement.company_id == c.id,
                                                      Announcement.priority.in_(("high", "medium")))
                           # latest day first, then the most important filing of that day
                           .order_by(func.date(Announcement.published_at).desc(),
                                     Announcement.priority_score.desc()).limit(1))
        row["latest_filing"] = None if latest is None else {
            "id": latest.id, "headline": (latest.extracted or {}).get("headline") or latest.category,
            "published_at": iso_utc(latest.published_at), "priority": latest.priority}
        row["unread_alerts"] = db.scalar(select(func.count(Alert.id)).where(
            Alert.company_id == c.id, Alert.seen.is_(False)))
        out.append(row)
    return out


@app.get("/api/symbols/search")
def search_symbols(q: str = Query(..., min_length=1, max_length=40)):
    """Any listed NSE company, not just FINN's own list: research generalises."""
    return nse_master.search(q)


class AddTicker(BaseModel):
    symbol: str
    name: str | None = None

    @field_validator("symbol")
    @classmethod
    def norm(cls, v: str) -> str:
        v = v.strip().upper().removesuffix(".NS")
        if not SYMBOL_RE.match(v):
            raise ValueError("Invalid NSE symbol")
        return v


@app.post("/api/portfolio", status_code=201)
def add_to_portfolio(body: AddTicker, db: Session = Depends(get_db)):
    company = db.scalar(select(Company).where(Company.nse_symbol == body.symbol))
    if company is None:
        listing = nse_master.lookup(body.symbol)
        if listing is None and not validate_nse_symbol(body.symbol):
            raise HTTPException(422, f"{body.symbol} is not a listed NSE symbol")
        legal = listing["legal_name"] if listing else None
        company = Company(nse_symbol=body.symbol,
                          name=body.name or (legal.removesuffix(" Limited") if legal else body.symbol),
                          meta={"legal_name": legal, "isin": listing["isin"]} if listing else {})
        db.add(company)
        db.flush()
    if db.scalar(select(PortfolioCompany).where(PortfolioCompany.company_id == company.id)):
        raise HTTPException(409, "Already in portfolio")
    db.add(PortfolioCompany(company_id=company.id))
    db.commit()
    refresh_prices(db, [company])
    return company_out(company, db)


@app.delete("/api/portfolio/{symbol}", status_code=204)
def remove_from_portfolio(symbol: str, db: Session = Depends(get_db)):
    company = get_company(db, symbol)
    pc = db.scalar(select(PortfolioCompany).where(PortfolioCompany.company_id == company.id))
    if pc is None:
        raise HTTPException(404, "Not in portfolio")
    db.delete(pc)
    db.commit()


# ---------- companies ----------
@app.get("/api/companies/search")
def search_companies(q: str, db: Session = Depends(get_db)):
    like = f"%{q.strip()}%"
    rows = db.scalars(select(Company).where(
        (Company.nse_symbol.ilike(like)) | (Company.name.ilike(like))).limit(10)).all()
    return [{"symbol": c.nse_symbol, "name": c.name, "sector": c.sector} for c in rows]


@app.get("/api/companies/{symbol}")
def get_company_detail(symbol: str, db: Session = Depends(get_db)):
    return company_out(get_company(db, symbol), db)


@app.get("/api/companies/{symbol}/prices")
def get_prices(symbol: str, days: int = 180, db: Session = Depends(get_db)):
    company = get_company(db, symbol)
    rows = price_rows(db, company.id, limit=min(max(days, 5), 1000))
    return {"symbol": company.nse_symbol, "data_type": "end_of_day",
            "rows": [{"date": r.trading_date.isoformat(), "open": r.open, "high": r.high,
                      "low": r.low, "close": r.close, "adj_close": r.adj_close,
                      "volume": r.volume} for r in rows]}


@app.get("/api/companies/{symbol}/chart")
def company_chart(symbol: str, days: int = Query(400, ge=10, le=1000), db: Session = Depends(get_db)):
    """Everything the interactive stock chart needs in one call: daily bars, the filings worth
    marking on the timeline, the NIFTY 50 benchmark, and 52-week figures."""
    company = get_company(db, symbol)
    rows = price_rows(db, company.id, limit=days)
    if not rows:
        raise HTTPException(404, f"No price history for {company.nse_symbol} yet")
    start = datetime.combine(rows[0].trading_date, datetime.min.time())
    anns = db.scalars(select(Announcement).where(
        Announcement.company_id == company.id, Announcement.published_at >= start,
        Announcement.priority.in_(("high", "medium"))).order_by(Announcement.published_at)).all()
    # pin each filing to the first session that could react to it (after-close filings -> next day)
    events = [{"date": reaction_session(a.published_at).isoformat(),
               "filed_at": iso_utc(a.published_at), "id": a.id, "priority": a.priority, "category": a.category,
               "headline": (a.extracted or {}).get("headline") or a.category,
               "url": a.document_url or a.original_url} for a in anns]
    bench = db.scalar(select(Company).where(Company.nse_symbol == "NIFTY50"))
    bench_rows = price_rows(db, bench.id, limit=days) if bench else []
    year = rows[-252:]
    return {
        "symbol": company.nse_symbol, "name": company.name, "sector": company.sector,
        "data_type": "end_of_day", "as_of": rows[-1].trading_date.isoformat(),
        "rows": [{"date": r.trading_date.isoformat(), "close": r.close, "adj_close": r.adj_close,
                  "high": r.high, "low": r.low, "volume": r.volume} for r in rows],
        "events": events,
        "benchmark": {"symbol": "NIFTY50", "name": "NIFTY 50",
                      "rows": [{"date": r.trading_date.isoformat(), "adj_close": r.adj_close} for r in bench_rows]},
        "week52": {"high": max(r.high for r in year), "low": min(r.low for r in year)},
    }


@app.get("/api/companies/{symbol}/announcements")
def company_announcements(symbol: str, days: int = Query(30, ge=1, le=365),
                          db: Session = Depends(get_db)):
    company = get_company(db, symbol)
    rows = db.scalars(select(Announcement).where(
        Announcement.company_id == company.id,
        Announcement.published_at >= utcnow_naive() - timedelta(days=days))
        .order_by(Announcement.published_at.desc())).all()
    return [announcement_out(a, company) for a in rows]


# ---------- push: digest + alerts ----------
@app.get("/api/digest")
def digest(hours: float = Query(24, gt=0, le=MAX_WINDOW_HOURS),
           since: datetime | None = None, until: datetime | None = None,
           widen: bool = False, db: Session = Depends(get_db)):
    """Window is [since, until) if given (ISO 8601, offset-aware), else the last `hours`.
    widen=true: if the last `hours` hold nothing, look back further (3, 7, then 30 days) and
    say so, so a quiet day opens on the latest briefing rather than an empty screen."""
    def to_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            raise HTTPException(400, "since/until need a UTC offset, e.g. 2026-10-27T09:00+05:30")
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    end = to_utc(until) if until else utcnow_naive()
    start = to_utc(since) if since else end - timedelta(hours=hours)
    if not start < end or end - start > timedelta(hours=MAX_WINDOW_HOURS):
        raise HTTPException(400, f"window must be positive and at most {MAX_WINDOW_HOURS} hours")
    result = build_digest(db, start, end)
    if widen and not since and result["counts"]["filings"] == 0:
        # open on the latest briefing: the whole IST day of the most recent portfolio filing
        latest = db.scalar(select(func.max(Announcement.published_at)).join(
            PortfolioCompany, PortfolioCompany.company_id == Announcement.company_id)
            .where(Announcement.published_at < end))
        if latest is not None and end - latest <= timedelta(hours=MAX_WINDOW_HOURS):
            day = latest.replace(tzinfo=timezone.utc).astimezone(IST).date()
            day_start = datetime.combine(day, datetime.min.time(), IST).astimezone(timezone.utc).replace(tzinfo=None)
            result = build_digest(db, day_start, end)
            result["window"]["widened_from_hours"] = hours
            result["window"]["latest_day"] = day.isoformat()
    result["as_of"] = {src: last_ok_run(db, src) for src in ("announcements", "prices")}
    return result


def last_ok_run(db: Session, source: str) -> str | None:
    """When FINN last successfully pulled this source: the freshness line on Today."""
    run = db.scalar(select(IngestRun).where(IngestRun.source == source, IngestRun.status.in_(("ok", "partial")))
                    .order_by(IngestRun.finished_at.desc()).limit(1))
    return iso_utc(run.finished_at) if run and run.finished_at else None


@app.post("/api/announcements/{announcement_id}/reviewed", status_code=204)
def announcement_reviewed(announcement_id: int, db: Session = Depends(get_db)):
    """'Done' on a Today card also clears the matching filing alert, so Today and Alerts agree."""
    ann = db.get(Announcement, announcement_id)
    if ann is None:
        raise HTTPException(404, "No such announcement")
    company = db.get(Company, ann.company_id)
    filed_on = ann.published_at.replace(tzinfo=timezone.utc).astimezone(IST).date()
    db.execute(update(Alert).where(Alert.dedupe_key == f"ann:{company.nse_symbol}:{ann.category}:{filed_on}")
               .values(seen=True))
    db.commit()


_ALERT_PREFIX = re.compile(r"^\S+\s+(volume [\d.]+x its \d+-day average|[+-][\d.]+%) on \d{1,2} \w{3},?\s*")
_ALERT_SUFFIX = re.compile(r"\s*\(your threshold [^)]*\)$")


def alert_title_detail(a: Alert, rule_type: str) -> tuple[str, str | None]:
    """A short headline plus the context line, for the alert list."""
    if rule_type == "announcement_category":
        body = a.message.split(": ", 1)[-1]
        title, _, detail = body.partition(" — ")
        return title, detail or None
    if rule_type == "volume_spike":
        title = f"{a.observed_value:.1f}× usual volume."
    else:
        title = f"{a.observed_value:+.1f}% in a day."
    detail = _ALERT_SUFFIX.sub("", _ALERT_PREFIX.sub("", a.message)).strip(" ,")
    return title, (detail[0].upper() + detail[1:]) if detail else None


def alert_out(a: Alert, company: Company, rule: AlertRule) -> dict:
    title, detail = alert_title_detail(a, rule.rule_type)
    return {"id": a.id, "symbol": company.nse_symbol, "name": company.name, "rule": rule.rule_type,
            "title": title, "detail": detail, "message": a.message, "observed": a.observed_value, "threshold": a.threshold_value,
            "as_of": a.as_of.isoformat() if a.as_of else None,
            "triggered_at": iso_utc(a.triggered_at), "source": a.source_reference, "seen": a.seen}


@app.get("/api/alerts")
def list_alerts(unseen: bool = False, limit: int = Query(50, ge=1, le=500),
                db: Session = Depends(get_db)):
    q = (select(Alert, Company, AlertRule).join(Company, Company.id == Alert.company_id)
         .join(AlertRule, AlertRule.id == Alert.rule_id))
    if unseen:
        q = q.where(Alert.seen.is_(False))
    rows = db.execute(q.order_by(Alert.as_of.desc(), Alert.triggered_at.desc()).limit(limit)).all()
    return [alert_out(a, c, r) for a, c, r in rows]


@app.post("/api/alerts/{alert_id}/seen", status_code=204)
def mark_seen(alert_id: int, db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(404, "No such alert")
    alert.seen = True
    db.commit()


@app.post("/api/alerts/seen-all", status_code=204)
def mark_all_seen(db: Session = Depends(get_db)):
    db.execute(update(Alert).values(seen=True))
    db.commit()


def rule_out(r: AlertRule) -> dict:
    return {"rule_type": r.rule_type, "threshold": r.threshold, "config": r.config, "enabled": r.enabled}


@app.get("/api/alert-rules")
def list_rules(db: Session = Depends(get_db)):
    return {"rules": [rule_out(r) for r in db.scalars(select(AlertRule))],
            "categories": list(CATEGORIES)}


class RuleUpdate(BaseModel):
    threshold: float | None = None
    enabled: bool | None = None
    categories: list[str] | None = None
    min_score: float | None = None


THRESHOLD_LIMITS = {"price_move": (0.5, 50.0), "volume_spike": (1.1, 20.0)}


@app.put("/api/alert-rules/{rule_type}")
def update_rule(rule_type: str, body: RuleUpdate, db: Session = Depends(get_db)):
    rule = db.scalar(select(AlertRule).where(AlertRule.rule_type == rule_type))
    if rule is None:
        raise HTTPException(404, "No such rule")
    if body.threshold is not None:
        lo, hi = THRESHOLD_LIMITS.get(rule_type, (None, None))
        if lo is None:
            raise HTTPException(400, f"{rule_type} has no numeric threshold")
        if not lo <= body.threshold <= hi:
            raise HTTPException(400, f"threshold must be between {lo} and {hi}")
        rule.threshold = body.threshold
    if body.enabled is not None:
        rule.enabled = body.enabled
    if body.categories is not None or body.min_score is not None:
        if rule_type != "announcement_category":
            raise HTTPException(400, "categories/min_score apply to announcement_category only")
        config = dict(rule.config or {})
        if body.categories is not None:
            bad = [c for c in body.categories if c.split(":", 1)[0] not in CATEGORIES]
            if bad:
                raise HTTPException(400, f"unknown categories: {bad}")
            config["categories"] = body.categories
        if body.min_score is not None:
            config["min_score"] = max(0.0, min(100.0, body.min_score))
        rule.config = config
    db.commit()
    # apply the new definition of "unusual" to the latest session straight away
    if rule_type == "announcement_category":
        evaluate_announcements(db, since=utcnow_naive() - timedelta(days=1))
    else:
        evaluate_market(db)
    return rule_out(rule)


@app.get("/api/companies/{symbol}/metrics")
def company_metrics(symbol: str, db: Session = Depends(get_db)):
    """Reported headline numbers FINN has extracted so far, ₹ crore, by period."""
    company = get_company(db, symbol)
    rows = db.scalars(select(FinancialMetric).where(FinancialMetric.company_id == company.id)
                      .order_by(FinancialMetric.period)).all()
    return [{"metric": r.metric, "period": r.period, "basis": r.basis, "value_cr": r.value_cr,
             "source": r.source_location, "announcement_id": r.source_announcement_id} for r in rows]


@app.get("/api/llm/usage")
def get_llm_usage(db: Session = Depends(get_db)):
    return llm_usage(db)


# ---------- pull: research ----------
_preparing: set[str] = set()


def _prepare_in_background(symbol: str, annual_report: bool) -> None:
    try:
        with SessionLocal() as db:
            company = get_or_create_company(db, symbol)
            if company is not None:
                prepare_company(db, company, annual_report=annual_report)
    except Exception:
        log.exception("research prepare failed for %s", symbol)
    finally:
        _preparing.discard(symbol)


def research_company(db: Session, symbol: str) -> Company:
    symbol = symbol.upper().removesuffix(".NS")
    if not SYMBOL_RE.match(symbol):
        raise HTTPException(400, "Invalid ticker format")
    company = get_or_create_company(db, symbol)
    if company is None:
        raise HTTPException(404, f"{symbol} is not a listed NSE symbol")
    return company


@app.get("/api/research")
def research_index(db: Session = Depends(get_db)):
    """Companies with research ready (or in progress), for the Research tab."""
    rows = db.execute(select(Company, func.count(FinancialDocument.id))
                      .join(FinancialDocument, FinancialDocument.company_id == Company.id)
                      .where(FinancialDocument.status.in_(("indexed", "guidance_extracted")))
                      .group_by(Company.id)).all()
    ready = []
    for c, n in rows:
        # the promise record (code-computed, no model call): what's been settled shows first
        counts = guidance_table(db, c.id)["counts"]
        record = {k: counts[k] for k in ("met", "exceeded", "missed", "on_track", "behind") if counts.get(k)}
        ready.append({"symbol": c.nse_symbol, "name": c.name, "sector": c.sector, "documents": n, "record": record,
                      "status": "preparing" if c.nse_symbol in _preparing else "ready"})
    settled = lambda r: sum(r["record"].get(k, 0) for k in ("met", "exceeded", "missed"))
    ready.sort(key=lambda r: (-settled(r), -sum(r["record"].values())))
    ready += [{"symbol": s, "status": "preparing"} for s in _preparing if s not in {r["symbol"] for r in ready}]
    return ready


@app.post("/api/research/{symbol}/prepare", status_code=202)
def research_prepare(symbol: str, background: BackgroundTasks, annual_report: bool = True,
                     db: Session = Depends(get_db)):
    """Works for any NSE ticker: discovers transcripts/annual reports, indexes them, extracts guidance."""
    company = research_company(db, symbol)
    if company.nse_symbol not in _preparing:
        _preparing.add(company.nse_symbol)
        background.add_task(_prepare_in_background, company.nse_symbol, annual_report)
    return {"symbol": company.nse_symbol, "status": "preparing"}


@app.get("/api/research/{symbol}")
def research_view(symbol: str, narrative: bool = False, db: Session = Depends(get_db)):
    """Everything computed by code: instant. The AI verdict is a separate call (/verdict) so the
    page never waits on a model. narrative=true still inlines it for scripts."""
    company = research_company(db, symbol)
    docs = research_documents(db, company.id)
    table = guidance_table(db, company.id)
    ready = any(d.status in ("indexed", "guidance_extracted") for d in docs)
    status = "preparing" if company.nse_symbol in _preparing else ("ready" if ready else "not_started")
    basis, series = actuals(db, company.id)
    quarters = [{"period": f"Q{q}FY{fy:02d}", **vals} for (fy, q), vals in sorted(series.items())][-8:]
    done = sum(d.status in ("indexed", "guidance_extracted") for d in docs)
    return {
        "company": {"symbol": company.nse_symbol, "name": company.name, "sector": company.sector,
                    "is_financial": company.is_financial,
                    "in_portfolio": db.scalar(select(PortfolioCompany).where(
                        PortfolioCompany.company_id == company.id)) is not None},
        "status": status,
        "progress": {"read": done, "total": len(docs),
                     "failed": sum(d.status == "failed" for d in docs)},
        "documents": [{"title": d.title, "type": d.doc_type, "period": d.period, "status": d.status,
                       "url": d.source_url, "error": d.error} for d in docs],
        "financials": {"basis": basis, "unit": "₹ crore", "quarters": quarters},
        "guidance": table,
        "statements": statements_for(db, company),
        "narrative": guidance_narrative(db, company.name, table) if narrative and table["rows"] else None,
    }


def statements_for(db: Session, company: Company) -> dict | None:
    st = db.scalar(select(CompanyStatements).where(CompanyStatements.company_id == company.id))
    if st is None:
        return None
    return {**analyse(st.tables, financial=bool(company.is_financial)), "basis": st.basis,
            "source": "screener.in's compilation of the annual filings", "fetched_at": st.fetched_at.isoformat()}


def statement_facts(statements: dict | None) -> list[str]:
    """The code-written reads, as citable facts for the bull and bear case."""
    if not statements:
        return []
    facts = [f"{x['label']}: " + (inr(x["value"]) if x["unit"] == "cr" else
                                  f"{x['value']}%" if x["unit"] == "pct" else f"{x['value']}×")
             for x in statements["snapshot"]]
    for sec in ("trajectory", "balance", "cash"):
        facts += statements[sec]["notes"]
    return facts


def research_documents(db: Session, company_id: int) -> list[FinancialDocument]:
    """The sources research reads: the latest five concall transcripts and the latest annual
    report (whatever their state, so progress is visible), plus anything else already read."""
    def latest(doc_type: str, n: int):
        return db.scalars(select(FinancialDocument).where(
            FinancialDocument.company_id == company_id, FinancialDocument.doc_type == doc_type)
            .order_by(FinancialDocument.published_on.desc()).limit(n)).all()
    read = db.scalars(select(FinancialDocument).where(
        FinancialDocument.company_id == company_id,
        FinancialDocument.doc_type.in_(("concall_transcript", "annual_report")),
        FinancialDocument.status.in_(("indexed", "guidance_extracted")))).all()
    seen, out = set(), []
    for d in [*latest("concall_transcript", 5), *latest("annual_report", 1), *read]:
        if d.id not in seen:
            seen.add(d.id)
            out.append(d)
    return sorted(out, key=lambda d: (d.doc_type != "concall_transcript", -(d.published_on.toordinal() if d.published_on else 0)))


@app.get("/api/research/{symbol}/verdict")
def research_verdict(symbol: str, db: Session = Depends(get_db)):
    """The model-written read-across of promised vs delivered (cached after the first call)."""
    company = research_company(db, symbol)
    table = guidance_table(db, company.id)
    return {"narrative": guidance_narrative(db, company.name, table) if table["rows"] else None}


@app.get("/api/research/{symbol}/business")
def research_business(symbol: str, db: Session = Depends(get_db)):
    """What the company does, its segments and mix, from its own annual report (cached)."""
    company = research_company(db, symbol)
    return {"business": business_snapshot(db, company)}


@app.get("/api/research/{symbol}/case")
def research_case(symbol: str, db: Session = Depends(get_db)):
    """Bull vs bear from FINN's computed facts and the company's own words (cached)."""
    company = research_company(db, symbol)
    facts = statement_facts(statements_for(db, company))
    return {"case": bull_bear(db, company, facts, guidance_table(db, company.id)["rows"])}


class Question(BaseModel):
    question: str
    announcement_id: int | None = None

    @field_validator("question")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not 3 <= len(v) <= 500:
            raise ValueError("question must be 3-500 characters")
        return v


@app.post("/api/research/{symbol}/ask")
def research_ask(symbol: str, body: Question, db: Session = Depends(get_db)):
    return ask(db, research_company(db, symbol), body.question, body.announcement_id)


# ---------- admin ----------
@app.post("/api/admin/enrich")
def admin_enrich(limit: int = Query(5, ge=1, le=50), db: Session = Depends(get_db)):
    return enrich_pending(db, limit=limit)


@app.post("/api/admin/refresh/prices")
def admin_refresh_prices(db: Session = Depends(get_db)):
    return refresh_prices(db)


@app.post("/api/admin/refresh/announcements")
def admin_refresh_announcements(db: Session = Depends(get_db)):
    return ingest_and_process(db)


@app.post("/api/admin/cycle")
def admin_cycle(prices: bool = False, db: Session = Depends(get_db)):
    return run_cycle(db, force_prices=prices)
