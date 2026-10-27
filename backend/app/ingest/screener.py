"""screener.in company page: links to primary documents (concall transcripts, annual reports)
and its standardised quarterly P&L table.

Only /company/ pages are read, which robots.txt allows. The documents themselves are fetched
from where screener links: company investor-relations sites and BSE's static file store. The
quarterly table is screener's compilation of exchange filings; it supplies the "delivered" side
of guidance tracking for past quarters, and FINN's own extraction from the results filing
overrides it whenever both exist."""
import calendar
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.extract.results import fiscal_quarter
from app.models import Company, FinancialDocument, FinancialMetric, IngestRun

log = logging.getLogger(__name__)

BASE = "https://www.screener.in/company/{symbol}/{suffix}"
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug",
                                      "sep", "oct", "nov", "dec"), start=1)}
# screener row label -> FINN metric (banks use "Revenue" / "Financing Profit")
ROW_METRICS = {"sales": "revenue", "revenue": "revenue", "operating profit": "operating_profit",
               "financing profit": "operating_profit", "profit before tax": "pbt", "net profit": "pat"}
SOURCE = "screener.in quarterly table"


@dataclass
class ScreenerPage:
    basis: str
    transcripts: list[dict]      # [{label, url, call_date}]
    annual_reports: list[dict]   # [{label, year, url}]
    quarters: dict               # {date: {metric: value_cr}}


def month_label_to_date(label: str, end_of_month: bool = False) -> date | None:
    m = re.match(r"([A-Za-z]{3})\w*\s+(\d{4})", label.strip())
    if not m or m.group(1).lower() not in MONTHS:
        return None
    y, mo = int(m.group(2)), MONTHS[m.group(1).lower()]
    if not end_of_month:
        return date(y, mo, 1)
    return date(y, mo, calendar.monthrange(y, mo)[1])


def _num(text: str) -> float | None:
    t = text.replace(",", "").replace("%", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def parse_page(html: str, basis: str) -> ScreenerPage:
    soup = BeautifulSoup(html, "html.parser")
    transcripts, reports = [], []
    for li in soup.select("#documents .concalls li"):
        a = li.find("a", title="Raw Transcript")
        label = li.select_one("div")
        if a and a.get("href") and label:
            transcripts.append({"label": label.get_text(strip=True), "url": a["href"],
                                "call_date": month_label_to_date(label.get_text(strip=True))})
    for a in soup.select("#documents .annual-reports a"):
        text = a.get_text(" ", strip=True)
        year = re.search(r"(20\d{2})", text)
        if a.get("href") and year:
            reports.append({"label": text.split(" from ")[0][:60], "year": int(year.group(1)), "url": a["href"]})

    quarters: dict = {}
    table = soup.select_one("#quarters table")
    if table is not None:
        headers = [th.get_text(strip=True) for th in table.select("thead th")][1:]
        dates = [month_label_to_date(h, end_of_month=True) for h in headers]
        for tr in table.select("tbody tr"):
            cells = [td.get_text(strip=True) for td in tr.select("td")]
            if not cells:
                continue
            metric = ROW_METRICS.get(cells[0].rstrip("+").strip().lower())
            if metric is None:
                continue
            for d, raw in zip(dates, cells[1:]):
                v = _num(raw)
                if d is not None and v is not None:
                    quarters.setdefault(d, {})[metric] = v
    return ScreenerPage(basis, transcripts, reports, quarters)


def fetch_page(symbol: str) -> ScreenerPage:
    """Consolidated view first (what investors track); standalone when a company has none."""
    headers = {"User-Agent": settings.nse_user_agent}
    for suffix, basis in (("consolidated/", "consolidated"), ("", "standalone")):
        r = httpx.get(BASE.format(symbol=quote(symbol, safe=""), suffix=suffix), headers=headers,
                      timeout=settings.http_timeout, follow_redirects=True)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        page = parse_page(r.text, basis)
        if page.quarters or page.transcripts:
            return page
    raise LookupError(f"screener.in has no page for {symbol}")


def sync_company(db: Session, company: Company, page: ScreenerPage | None = None) -> dict:
    run = IngestRun(source="documents", detail={"symbol": company.nse_symbol})
    db.add(run)
    db.commit()
    try:
        page = page or fetch_page(company.nse_symbol)
        for t in page.transcripts:
            _upsert_doc(db, company, "concall_transcript", f"Concall transcript, {t['label']}", t["url"],
                        call_period(t["call_date"]) if t["call_date"] else None, t["call_date"])
        for a in page.annual_reports:
            _upsert_doc(db, company, "annual_report", a["label"], a["url"], f"FY{a['year'] % 100:02d}",
                        date(a["year"], 3, 31))
        n_metrics = 0
        for d, values in page.quarters.items():
            if d.month not in (3, 6, 9, 12):
                continue
            for metric, value in values.items():
                stmt = insert(FinancialMetric).values(
                    company_id=company.id, metric=metric, period=fiscal_quarter(d), value_cr=value,
                    basis=page.basis, source_location=SOURCE)
                # FINN's own extraction from the filing wins over the compiled table
                n_metrics += db.execute(stmt.on_conflict_do_nothing()).rowcount
        db.commit()
        run.status = "ok"
        run.detail = {**run.detail, "basis": page.basis, "transcripts": len(page.transcripts),
                      "annual_reports": len(page.annual_reports), "new_metrics": n_metrics}
    except Exception as exc:
        db.rollback()
        log.exception("screener sync failed for %s", company.nse_symbol)
        run.status, run.detail = "failed", {**(run.detail or {}), "error": str(exc)[:300]}
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": run.status, **run.detail}


def call_period(call_date: date) -> str:
    """A call held in Jul/Aug discusses Q1; Oct/Nov Q2; Jan/Feb Q3; Apr/May Q4 (of the FY just ended)."""
    m, y = call_date.month, call_date.year
    if m in (7, 8, 9):
        return fiscal_quarter(date(y, 6, 30))
    if m in (10, 11, 12):
        return fiscal_quarter(date(y, 9, 30))
    if m in (1, 2, 3):
        return fiscal_quarter(date(y - 1, 12, 31))
    return fiscal_quarter(date(y, 3, 31))


def _upsert_doc(db: Session, company: Company, doc_type: str, title: str, url: str,
                period: str | None, published_on: date | None) -> None:
    doc = db.scalar(select(FinancialDocument).where(FinancialDocument.company_id == company.id,
                                                    FinancialDocument.source_url == url))
    if doc is None:
        db.add(FinancialDocument(company_id=company.id, doc_type=doc_type, title=title, source_url=url,
                                 period=period, published_on=published_on, status="discovered"))
    elif doc.doc_type != doc_type:
        doc.doc_type, doc.title, doc.period, doc.published_on = doc_type, title, period, published_on
