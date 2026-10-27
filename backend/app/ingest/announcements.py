"""NSE corporate announcements via the exchange's official RSS feed.

The feed holds roughly the last day of filings across every listed company (TTL 5 min), so
FINN builds its own history by polling it. Each filing is stored once: the exchange often
re-transmits the same item, so the dedupe key is company + link + subject + text."""
import hashlib
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Announcement, Company, IngestRun

log = logging.getLogger(__name__)

FEED_URL = "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"
IST = timezone(timedelta(hours=5, minutes=30))
_SUFFIX = re.compile(r"\s+(limited|ltd)$")


@dataclass(frozen=True)
class FeedItem:
    company_name: str
    link: str
    text: str
    subject: str | None
    published_at: datetime  # naive UTC, the convention for every stored timestamp


def norm_name(name: str) -> str:
    """'Dr. Reddy's Laboratories Limited' -> 'dr reddy s laboratories'. Exact match only:
    a prefix match would file Mahindra & Mahindra Financial Services under M&M."""
    s = name.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return _SUFFIX.sub("", " ".join(s.split()))


PUB_DATE_FORMATS = ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M")  # both appear in the same feed


def _parse_pub_date(value: str) -> datetime | None:
    for fmt in PUB_DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def parse_feed(content: bytes) -> list[FeedItem]:
    items = []
    for node in ET.fromstring(content).iterfind("./channel/item"):
        title = (node.findtext("title") or "").strip()
        desc = (node.findtext("description") or "").strip()
        pub = (node.findtext("pubDate") or "").strip()
        if not (title and pub):
            continue
        local = _parse_pub_date(pub)
        if local is None:
            log.warning("unparseable pubDate %r", pub)
            continue
        text, _, subject = desc.partition("|SUBJECT:")
        items.append(FeedItem(title, (node.findtext("link") or "").strip(), text.strip(),
                              subject.strip() or None,
                              local.astimezone(timezone.utc).replace(tzinfo=None)))
    return items


def fetch_feed(attempts: int = 3) -> bytes:
    """The archive server sometimes closes the connection mid-body (seen in practice), so a
    response only counts once it parses as XML."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            r = httpx.get(FEED_URL, headers={"User-Agent": settings.nse_user_agent},
                          timeout=settings.http_timeout, follow_redirects=True)
            r.raise_for_status()
            ET.fromstring(r.content)
            return r.content
        except (httpx.HTTPError, ET.ParseError) as exc:
            last_error = exc
            log.warning("feed fetch attempt %d failed: %s", attempt + 1, exc)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"NSE feed unavailable after {attempts} attempts: {last_error}")


def company_index(db: Session) -> dict[str, Company]:
    index: dict[str, Company] = {}
    for c in db.scalars(select(Company)):
        for name in ((c.meta or {}).get("legal_name"), c.name):
            if name:
                index.setdefault(norm_name(name), c)
    return index


def _source_id(company_id: int, item: FeedItem) -> str:
    key = f"{company_id}|{item.link}|{item.subject}|{item.text}"
    return hashlib.sha1(key.encode()).hexdigest()


def refresh_announcements(db: Session, content: bytes | None = None) -> dict:
    """Fetch (or replay `content`), keep items for known companies, insert new ones."""
    run = IngestRun(source="announcements")
    db.add(run)
    db.commit()
    detail: dict = {"items": 0, "matched": 0, "new": 0}
    new_ids: list[int] = []
    try:
        items = parse_feed(content if content is not None else fetch_feed())
        index = company_index(db)
        detail["items"] = len(items)
        for item in items:
            company = index.get(norm_name(item.company_name))
            if company is None:
                continue
            detail["matched"] += 1
            stmt = insert(Announcement).values(
                company_id=company.id, source="nse", source_id=_source_id(company.id, item),
                title=item.text or item.subject or "(no description)",
                exchange_category=item.subject, published_at=item.published_at,
                original_url=item.link or None,
                document_url=item.link if item.link.lower().endswith(".pdf") else None,
                raw_text=item.text,
            ).on_conflict_do_nothing(index_elements=["source", "source_id"]).returning(Announcement.id)
            new_id = db.execute(stmt).scalar()
            if new_id is not None:
                new_ids.append(new_id)
        db.commit()
        detail["new"] = len(new_ids)
        run.status = "ok"
    except Exception as exc:  # network, feed format change
        db.rollback()
        log.exception("announcement refresh failed")
        run.status = "failed"
        detail["error"] = str(exc)
    run.detail = detail
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": run.status, **detail, "new_ids": new_ids}
