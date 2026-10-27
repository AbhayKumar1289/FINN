"""Primary-document index: page-aware chunks in SQLite FTS5 (BM25 ranking).

Why not embeddings: transcripts and annual reports are full of exact terms investors search
for ("EBITDA margin", "order inflow", "capex", "FY27"), BM25 handles those well, it needs no
extra service or model calls, and it ships inside the same SQLite file."""
import re
from datetime import datetime, timezone

from sqlalchemy import delete, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.extract.documents import fetch_pdf, page_texts
from app.models import DocumentChunk, FinancialDocument

CHUNK_CHARS = 1500
OVERLAP = 200
MAX_PAGES = {"annual_report": 400, "concall_transcript": 80}
STOPWORDS = set("a an and are as at be by did do does for from has have how in is it its of on or "
                "the their this to was were what when where which who why will with".split())


def ensure_fts(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5("
                          "text, content='document_chunks', content_rowid='id', tokenize='porter unicode61')"))


def _clean(page: str) -> str:
    page = re.sub(r"-\n(?=[a-z])", "", page)  # re-join hyphenated line breaks
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{2,}", "\n", page)).strip()


def chunk_pages(pages: list[str]) -> list[tuple[int, str]]:
    """(1-based page number, text) chunks; pages are never merged, so citations stay exact."""
    out = []
    for i, raw in enumerate(pages, start=1):
        page = _clean(raw)
        if len(page) < 80:
            continue
        start = 0
        while start < len(page):
            end = min(len(page), start + CHUNK_CHARS)
            if end < len(page):  # prefer to break at a sentence end
                cut = page.rfind(". ", start + CHUNK_CHARS // 2, end)
                end = cut + 1 if cut != -1 else end
            out.append((i, page[start:end].strip()))
            if end >= len(page):
                break
            start = max(end - OVERLAP, start + 1)
    return out


def index_document(db: Session, doc: FinancialDocument) -> int:
    if doc.status == "indexed":
        return 0
    doc, data = fetch_pdf(db, doc.company_id, doc.source_url, doc.doc_type, doc.title, doc.period)
    pages = page_texts(data)[: MAX_PAGES.get(doc.doc_type, 200)]
    old = [r for (r,) in db.execute(select(DocumentChunk.id).where(DocumentChunk.document_id == doc.id))]
    for rid in old:
        db.execute(text("INSERT INTO chunk_fts(chunk_fts, rowid, text) "
                        "SELECT 'delete', id, text FROM document_chunks WHERE id = :id"), {"id": rid})
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    chunks = chunk_pages(pages)
    if not chunks:
        doc.status, doc.error = "failed", "no extractable text (scanned PDF?)"
        db.commit()
        return 0
    for n, (page_no, body) in enumerate(chunks):
        row = DocumentChunk(document_id=doc.id, chunk_index=n, text=body, page_number=page_no)
        db.add(row)
        db.flush()
        db.execute(text("INSERT INTO chunk_fts(rowid, text) VALUES (:id, :t)"), {"id": row.id, "t": body})
    doc.status, doc.error, doc.processed_at = "indexed", None, datetime.now(timezone.utc)
    db.commit()
    return len(chunks)


def fts_query(question: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z0-9]+", question.lower()) if w not in STOPWORDS and len(w) > 1]
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(words)) or '""'


def search(db: Session, company_id: int, question: str, k: int = 8,
           doc_types: tuple[str, ...] | None = None) -> list[dict]:
    sql = ("SELECT c.id, c.text, c.page_number, d.id, d.title, d.doc_type, d.period, d.source_url, "
           "bm25(chunk_fts) AS score FROM chunk_fts JOIN document_chunks c ON c.id = chunk_fts.rowid "
           "JOIN financial_documents d ON d.id = c.document_id "
           "WHERE chunk_fts MATCH :q AND d.company_id = :cid")
    params: dict = {"q": fts_query(question), "cid": company_id, "k": k}
    if doc_types:
        sql += " AND d.doc_type IN (%s)" % ",".join(f":t{i}" for i in range(len(doc_types)))
        params |= {f"t{i}": t for i, t in enumerate(doc_types)}
    rows = db.execute(text(sql + " ORDER BY score LIMIT :k"), params).all()
    return [{"chunk_id": r[0], "text": r[1], "page": r[2], "document_id": r[3], "title": r[4],
             "doc_type": r[5], "period": r[6], "url": r[7]} for r in rows]
