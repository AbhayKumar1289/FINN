"""Management change: who is coming in, who is leaving, and a short background.

Bio sources, best first, and every bio says which one it used:
  1. the filing itself (SEBI requires a brief profile with most appointments);
  2. Wikipedia, when WIKI_CONTACT is set (Wikimedia's bot policy needs a contact);
  3. the strong model's own knowledge, labelled unverified, and allowed to say "unknown".
Gemini's Google Search grounding would slot in before 3 on a key with search quota."""
import logging
import re

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.extract.documents import fetch_pdf, page_texts, subset_pdf
from app.llm.client import generate, pdf_part
from app.models import Announcement, Company

log = logging.getLogger(__name__)

MAX_PAGES = 6

CHANGES_SCHEMA = {"type": "object", "properties": {"changes": {"type": "array", "items": {
    "type": "object", "properties": {
        "name": {"type": "string", "description": "person's name without honorific"},
        "role": {"type": "string"},
        "direction": {"type": "string", "enum": ["appointment", "exit", "redesignation"]},
        "effective_date": {"type": "string", "nullable": True, "description": "YYYY-MM-DD"},
        "reason": {"type": "string", "nullable": True},
        "profile": {"type": "string", "nullable": True,
                    "description": "brief profile copied from the filing, if the filing has one"},
        "profile_reference": {"type": "string", "nullable": True,
                              "description": "where the filing says the profile was given, if elsewhere"}},
    "required": ["name", "role", "direction"]}}}, "required": ["changes"]}

CHANGES_SYSTEM = ("You read Indian stock-exchange filings about management and board changes. List each "
                  "person whose position changes. Skip people only listed as contacts. Copy names, roles "
                  "and any profile text from the filing; do not add outside information.")

BIO_SCHEMA = {"type": "object", "properties": {
    "known": {"type": "boolean"},
    "bio": {"type": "string", "nullable": True,
            "description": "2-3 sentences: prior roles and employers, tenure, education if well known"},
    "confidence": {"type": "string", "enum": ["high", "medium", "low"]}},
    "required": ["known", "confidence"]}

BIO_SYSTEM = ("You give short professional backgrounds of Indian business executives who have just been "
              "appointed to a new role. Describe their career before this appointment, in the past tense "
              "(your knowledge may predate the move, so never describe an earlier job as current). State "
              "only facts you are confident of. If you do not clearly know this specific person, return "
              "known=false rather than guessing. No opinions.")


def _wikipedia_bio(name: str, company: str) -> dict | None:
    if not settings.wiki_contact:
        return None
    headers = {"User-Agent": f"{settings.nse_user_agent} ({settings.wiki_contact})"}
    try:
        r = httpx.get("https://en.wikipedia.org/w/api.php", headers=headers, timeout=20,
                      params={"action": "query", "list": "search", "srsearch": f"{name} {company}",
                              "format": "json", "srlimit": 3})
        r.raise_for_status()
        surname = name.split()[-1].lower()
        title = next((h["title"] for h in r.json()["query"]["search"] if surname in h["title"].lower()), None)
        if title is None:
            return None
        s = httpx.get("https://en.wikipedia.org/api/rest_v1/page/summary/" + title.replace(" ", "_"),
                      headers=headers, timeout=20).json()
        extract = s.get("extract") or ""
        if surname not in extract.lower():
            return None
        return {"bio": " ".join(re.split(r"(?<=\.)\s+", extract)[:3]), "source": "wikipedia",
                "source_url": (s.get("content_urls") or {}).get("desktop", {}).get("page"),
                "verified": True}
    except Exception:
        log.exception("wikipedia lookup failed for %s", name)
        return None


def _model_bio(db: Session, name: str, role: str, company: str) -> dict:
    res = generate(db, "bio_knowledge",
                   [{"text": f"{name}, {role} at {company}. Professional background?"}],
                   tier="strong", system=BIO_SYSTEM, schema=BIO_SCHEMA)
    d = res.data
    if not d.get("known") or not d.get("bio") or d.get("confidence") == "low":
        return {"bio": None, "source": "model_knowledge", "verified": False,
                "note": "No reliable background found; check the company's earlier filings."}
    return {"bio": d["bio"], "source": "model_knowledge", "verified": False,
            "confidence": d.get("confidence"),
            "note": "From the model's general knowledge, not a cited source. Verify before relying on it."}


def extract_people(db: Session, ann: Announcement) -> dict:
    company = db.get(Company, ann.company_id)
    _, data = fetch_pdf(db, company.id, ann.document_url, "announcement", ann.summary or ann.title)
    n = len(page_texts(data))
    res = generate(db, "people_extract",
                   [pdf_part(subset_pdf(data, list(range(min(n, MAX_PAGES))))),
                    {"text": f"Company: {company.name}."}],
                   tier="cheap", system=CHANGES_SYSTEM, schema=CHANGES_SCHEMA)
    changes = res.data.get("changes") or []
    for ch in changes:
        if ch.get("direction") == "exit":
            continue
        if ch.get("profile"):
            ch["background"] = {"bio": ch["profile"], "source": "filing", "verified": True}
            continue
        ch["background"] = _wikipedia_bio(ch["name"], company.name) or \
            _model_bio(db, ch["name"], ch["role"], company.name)
    incoming = next((c for c in changes if c.get("direction") != "exit"), None)
    outgoing = next((c for c in changes if c.get("direction") == "exit"), None)
    return {"changes": changes, "line": _people_line(incoming, outgoing)}


def _people_line(incoming: dict | None, outgoing: dict | None) -> str | None:
    if incoming and outgoing:
        return f"{incoming['name']} takes over as {incoming['role']} from {outgoing['name']}"
    if incoming:
        return f"{incoming['name']} appointed {incoming['role']}"
    if outgoing:
        return f"{outgoing['name']} steps down as {outgoing['role']}"
    return None
