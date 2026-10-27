"""Windowed digest: every portfolio filing in [start, end), ranked, with routine collapsed.

Filings about the same company and category in the window are one event (Maruti's results
filing, results press release and results deck), so they become one card with `related`."""
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Announcement, Company, PortfolioCompany
from app.pipeline.present import CATEGORY_LABEL, SUBTYPE_LABEL


def iso_utc(dt: datetime | None) -> str | None:
    return None if dt is None else dt.replace(tzinfo=timezone.utc).isoformat()


def _subtype(ann: Announcement) -> str | None:
    return ((ann.extracted or {}).get("classification") or {}).get("subtype")


def announcement_out(ann: Announcement, company: Company) -> dict:
    sub = _subtype(ann)
    return {
        "id": ann.id,
        "company": {"symbol": company.nse_symbol, "name": company.name, "sector": company.sector},
        "category": ann.category, "subtype": sub,
        "category_label": CATEGORY_LABEL.get(ann.category, "Filing"),
        "label": SUBTYPE_LABEL.get((ann.category, sub), CATEGORY_LABEL.get(ann.category, "Filing")),
        "headline": (ann.extracted or {}).get("headline"),
        "summary": ann.summary, "why_it_matters": ann.why_it_matters,
        "priority": ann.priority, "score": ann.priority_score, "reasons": ann.priority_reasons or [],
        "published_at": iso_utc(ann.published_at), "exchange_category": ann.exchange_category,
        "document_url": ann.document_url, "source_url": ann.original_url,
        "reaction": (ann.extracted or {}).get("reaction"),
        # AI layer (chunk 3): present only for results filings / management changes
        "results": (ann.extracted or {}).get("results"),
        "people": (ann.extracted or {}).get("people"),
    }


def build_digest(db: Session, start: datetime, end: datetime) -> dict:
    rows = db.execute(
        select(Announcement, Company).join(Company, Company.id == Announcement.company_id)
        .join(PortfolioCompany, PortfolioCompany.company_id == Company.id)
        .where(Announcement.published_at >= start, Announcement.published_at < end,
               Announcement.processing_status == "processed")).all()

    groups: dict[tuple, list] = defaultdict(list)
    for ann, company in rows:
        groups[(company.id, ann.category)].append((ann, company))

    cards, routine = [], defaultdict(lambda: {"count": 0, "labels": set()})
    counts = {"high": 0, "medium": 0, "low": 0}
    for items in groups.values():
        items.sort(key=lambda x: (-(x[0].priority_score or 0), x[0].published_at))
        lead, company = items[0]
        counts[lead.priority or "low"] += 1
        if lead.priority == "low":
            r = routine[company.nse_symbol]
            r["name"] = company.name
            r["count"] += len(items)
            r["labels"].update(SUBTYPE_LABEL.get((a.category, _subtype(a)), CATEGORY_LABEL.get(a.category))
                               for a, _ in items)
            continue
        card = announcement_out(lead, company)
        card["related"] = [{"id": a.id, "label": SUBTYPE_LABEL.get((a.category, _subtype(a)), a.category),
                            "summary": a.summary, "published_at": iso_utc(a.published_at),
                            "url": a.document_url or a.original_url} for a, _ in items[1:]]
        cards.append(card)

    # highest score first; newest first among equals (sorts are stable)
    cards.sort(key=lambda c: c["published_at"], reverse=True)
    cards.sort(key=lambda c: -(c["score"] or 0))
    routine_list = sorted(({"symbol": s, "name": v["name"], "count": v["count"],
                            "labels": sorted(l for l in v["labels"] if l)} for s, v in routine.items()),
                          key=lambda r: -r["count"])
    n_routine = sum(r["count"] for r in routine_list)
    return {
        "window": {"start": iso_utc(start), "end": iso_utc(end),
                   "hours": round((end - start).total_seconds() / 3600, 1)},
        "generated_at": iso_utc(datetime.now(timezone.utc).replace(tzinfo=None)),
        "counts": {"filings": len(rows), "events": len(groups), **counts},
        "cards": cards,
        "routine": {"count": n_routine, "companies": routine_list,
                    "line": (f"{n_routine} routine filing{'s' if n_routine != 1 else ''} across "
                             f"{len(routine_list)} compan{'ies' if len(routine_list) != 1 else 'y'}")
                    if n_routine else None},
    }
