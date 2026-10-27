"""Grounded Q&A over the company's own transcripts and annual reports. The model sees only
retrieved excerpts, must cite them, and must say so when they don't answer the question."""
import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.client import generate
from app.models import Announcement, Company, ResearchResult
from app.research.delivery import guidance_table
from app.research.index import search

SCHEMA = {"type": "object", "properties": {
    "found": {"type": "boolean", "description": "false if the excerpts do not answer the question"},
    "answer": {"type": "string", "description": "concise answer, citing excerpts like [2]"},
    "citations": {"type": "array", "items": {"type": "integer"}}},
    "required": ["found", "answer", "citations"]}

SYSTEM = ("You answer an investor's question about a company using ONLY the numbered excerpts from its "
          "annual reports and earnings-call transcripts. Do not use outside knowledge, news or broker views. "
          "Cite excerpts inline like [2]. Quote numbers exactly as written. If the excerpts don't answer the "
          "question, set found=false and say what is missing. Keep it under 150 words.")


def event_context(db: Session, announcement_id: int | None) -> str:
    """A pushed card opens a research thread already scoped to its event."""
    if not announcement_id:
        return ""
    ann = db.get(Announcement, announcement_id)
    if ann is None:
        return ""
    ex = ann.extracted or {}
    detail = (ex.get("results") or {}).get("line") or (ex.get("people") or {}).get("line") or ann.summary
    return f"{ex.get('headline') or ann.category}: {detail}"


SCORED = ("met", "missed", "exceeded", "on_track", "behind")


def computed_facts(db: Session, company: Company, announcement_id: int | None) -> list[dict]:
    """FINN's own derived facts (results-filing numbers, scored guidance), handed to the model
    as citable [F#] items so it never re-derives or misdates them from prose."""
    facts = []
    ann = db.get(Announcement, announcement_id) if announcement_id else None
    results = ((ann.extracted or {}).get("results") if ann else None) or {}
    if results:
        facts.append({"text": f"{results['period']} results ({results['basis']}, from the results filing): "
                              f"{results['line']}", "title": "Results filing", "url": ann.document_url})
    for r in guidance_table(db, company.id)["rows"]:
        if r["status"] in SCORED:
            facts.append({"text": f"Guidance stated on the {r['stated_in']} call: \"{r['quote']}\" → {r['status'].replace('_', ' ')}"
                                  f" (actual {r['actual']}% over {r['measured_over']}, target {r['target']})",
                          "title": r["source"]["title"], "page": r["source"]["page"], "url": r["source"]["url"]})
    return facts[:8]


def ask(db: Session, company: Company, question: str, announcement_id: int | None = None, k: int = 8) -> dict:
    context = event_context(db, announcement_id)
    facts = computed_facts(db, company, announcement_id)
    hits = search(db, company.id, f"{question} {context}", k=k)
    if not hits and not facts:
        return {"found": False, "answer": "Nothing in the indexed transcripts or annual reports matches this "
                                          "question yet. Prepare research for this company first.",
                "sources": [], "cached": False}
    fact_texts = [f["text"] for f in facts]
    key = hashlib.sha256(f"{company.id}|{question}|{context}|{[h['chunk_id'] for h in hits]}|{fact_texts}"
                         .encode()).hexdigest()
    prior = db.scalar(select(ResearchResult).where(ResearchResult.cache_key == key))
    if prior is not None:
        return {**prior.result, "sources": prior.evidence, "cached": True}

    # facts are numbered after the excerpts so every citation is a single integer
    items = [*hits, *facts]
    excerpts = "\n\n".join(f"[{i}] ({h['title']}, p.{h['page']})\n{h['text']}" for i, h in enumerate(hits, start=1))
    fact_block = "\n".join(f"[{len(hits) + i}] {f['text']}" for i, f in enumerate(facts, start=1))
    prompt = (f"Company: {company.name}\n" + (f"Event the investor is looking at: {context}\n" if context else "")
              + f"Question: {question}\n\n"
              + (f"Facts computed by FINN from the filings (authoritative, cite like excerpts):\n{fact_block}\n\n"
                 if facts else "")
              + f"Excerpts:\n{excerpts or '(none)'}")
    res = generate(db, "research_qa", [{"text": prompt}], tier="strong", system=SYSTEM, schema=SCHEMA,
                   thinking="low")
    cited = sorted({c for c in res.data.get("citations") or [] if 1 <= c <= len(items)})
    sources = [{"n": c, "title": items[c - 1]["title"], "page": items[c - 1].get("page"),
                "url": items[c - 1].get("url"), "kind": "excerpt" if c <= len(hits) else "finn_fact",
                "excerpt": items[c - 1]["text"][:300]} for c in cited]
    result = {"found": bool(res.data.get("found")), "answer": res.data.get("answer", ""), "model": res.model}
    db.add(ResearchResult(company_id=company.id, question=question, module="qa", result=result,
                          evidence=sources, cache_key=key))
    db.commit()
    return {**result, "sources": sources, "cached": False}
