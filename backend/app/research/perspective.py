"""The two research sections that need reading, not arithmetic: what the business is, and the
bull and bear case. Both are grounded the same way as Q&A: the model sees numbered excerpts from
the company's own annual report and transcripts (plus FINN's computed facts for the case), must
cite them, and code drops anything whose citation doesn't check out."""
import re

from sqlalchemy.orm import Session

from app.llm.client import generate
from app.models import Company
from app.research.index import search

BUSINESS_QUERY = ("business segment segments revenue share contribution products brands portfolio "
                  "manufacturing plants capacity distribution customers geography international market share")
CASE_QUERY = ("outlook demand growth opportunity margin pressure competition risk headwind pricing "
              "capacity expansion market share challenge")

BUSINESS_SCHEMA = {"type": "object", "properties": {
    "summary": {"type": "string", "description": "two sentences: what the company does and how it makes money"},
    "segments": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"},
        "share_pct": {"type": "number", "nullable": True,
                      "description": "share of revenue exactly as stated in the excerpt, else null"},
        "detail": {"type": "string", "description": "one short line"},
        "ref": {"type": "integer"}}, "required": ["name", "detail", "ref"]}},
    "facts": {"type": "array", "items": {"type": "object", "properties": {
        "text": {"type": "string", "description": "one concrete fact: scale, plants, reach, mix, market position"},
        "ref": {"type": "integer"}}, "required": ["text", "ref"]}}},
    "required": ["summary", "segments", "facts"]}

BUSINESS_SYSTEM = ("You describe a listed Indian company's business using ONLY the numbered excerpts from its "
                   "annual report and earnings calls. No outside knowledge. Every segment and fact cites one "
                   "excerpt by number. Give a revenue share only if the excerpt states it. At most 5 segments "
                   "and 4 facts; prefer the most recent figures. Plain English, no marketing language.")

CASE_SCHEMA = {"type": "object", "properties": {
    side: {"type": "array", "items": {"type": "object", "properties": {
        "point": {"type": "string", "description": "one sentence, specific, with the number if there is one"},
        "refs": {"type": "array", "items": {"type": "integer"}}}, "required": ["point", "refs"]}}
    for side in ("bull", "bear")}, "required": ["bull", "bear"]}

CASE_SYSTEM = ("You write a tight bull case and bear case for a listed Indian company for an investor, using "
               "ONLY the numbered items: facts computed by FINN from the financial statements and excerpts "
               "from the company's own transcripts and annual report. No outside knowledge, news, price "
               "targets or recommendations. Exactly three points a side, each one sentence, each citing the "
               "items it rests on. The bear case must be as strong as the bull case: look for weak cash "
               "conversion, compressing margins, missed guidance, rising debt or working capital, and risks "
               "management itself names.")


def _plain(text: str) -> str:
    """Citations are shown as chips; drop the model's inline [2, 3] markers."""
    return re.sub(r"\s*\[\d+(?:\s*,\s*\d+)*\]", "", text or "").strip()


def _excerpt_block(hits: list[dict], start: int = 1) -> str:
    return "\n\n".join(f"[{i}] ({h['title']}, p.{h['page']})\n{h['text'][:1400]}" for i, h in enumerate(hits, start))


def _source(h: dict, n: int) -> dict:
    return {"n": n, "title": h["title"], "page": h.get("page"), "url": h.get("url"),
            "kind": h.get("kind", "excerpt"), "excerpt": h["text"][:280]}


def business_snapshot(db: Session, company: Company) -> dict | None:
    hits = search(db, company.id, BUSINESS_QUERY, k=10, doc_types=("annual_report",))
    if len(hits) < 4:  # no annual report indexed: the latest calls describe the business too
        hits += search(db, company.id, BUSINESS_QUERY, k=10 - len(hits), doc_types=("concall_transcript",))
    if not hits:
        return None
    res = generate(db, "business_snapshot",
                   [{"text": f"Company: {company.name}\n\nExcerpts:\n{_excerpt_block(hits)}"}],
                   tier="strong", system=BUSINESS_SYSTEM, schema=BUSINESS_SCHEMA, thinking="low")
    ok = lambda n: isinstance(n, int) and 1 <= n <= len(hits)
    segments = []
    for s in res.data.get("segments") or []:
        if not ok(s.get("ref")):
            continue
        share = s.get("share_pct")
        # a revenue share must be printed in the cited excerpt, or it isn't shown
        if share is not None and not re.search(rf"(?<![\d.]){share:g}\s*%", hits[s["ref"] - 1]["text"]):
            share = None
        segments.append({"name": s["name"], "share_pct": share, "detail": _plain(s["detail"]), "ref": s["ref"]})
    facts = [{"text": _plain(f["text"]), "ref": f["ref"]} for f in res.data.get("facts") or [] if ok(f.get("ref"))]
    cited = sorted({x["ref"] for x in segments + facts})
    return {"summary": _plain(res.data.get("summary", "")), "segments": segments, "facts": facts,
            "sources": [_source(hits[n - 1], n) for n in cited], "model": res.model}


def bull_bear(db: Session, company: Company, facts: list[str], guidance_rows: list[dict]) -> dict | None:
    items = [{"text": f, "title": "FINN, from the annual statements", "kind": "finn_fact"} for f in facts]
    for r in guidance_rows:
        if r["status"] in ("met", "missed", "exceeded", "on_track", "behind") and r.get("same_as") is None:
            items.append({"text": f"Guidance ({r['stated_in']} call) \"{r['quote']}\" → {r['status'].replace('_', ' ')}: "
                                  f"actual {r['actual']}% over {r['measured_over']} vs target {r['target']}",
                          "title": r["source"]["title"], "page": r["source"]["page"], "url": r["source"]["url"],
                          "kind": "finn_fact"})
    hits = search(db, company.id, CASE_QUERY, k=8, doc_types=("concall_transcript",))
    hits += search(db, company.id, "risk risks challenges outlook", k=3, doc_types=("annual_report",))
    items += hits
    if len(items) < 3:
        return None
    facts_block = "\n".join(f"[{i}] {it['text']}" for i, it in enumerate(items, 1) if it.get("kind") == "finn_fact")
    ex_start = sum(1 for it in items if it.get("kind") == "finn_fact") + 1
    prompt = (f"Company: {company.name}\n\nFacts computed by FINN (authoritative):\n{facts_block or '(none)'}\n\n"
              f"Excerpts:\n{_excerpt_block(hits, ex_start) or '(none)'}")
    res = generate(db, "bull_bear", [{"text": prompt}], tier="strong", system=CASE_SYSTEM, schema=CASE_SCHEMA,
                   thinking="low")
    out: dict = {"model": res.model}
    used: set[int] = set()
    for side in ("bull", "bear"):
        points = []
        for p in res.data.get(side) or []:
            refs = sorted({n for n in p.get("refs") or [] if isinstance(n, int) and 1 <= n <= len(items)})
            if refs:  # an uncited point is an opinion, not analysis: dropped
                points.append({"point": _plain(p["point"]), "refs": refs})
                used.update(refs)
        out[side] = points[:3]
    out["sources"] = [_source(items[n - 1], n) for n in sorted(used)]
    return out
