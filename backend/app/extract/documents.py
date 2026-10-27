"""Download filing PDFs once, keep them on disk keyed by content hash, and cut page subsets
so the model only ever sees the pages that matter."""
import hashlib
import io
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pypdf
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import FinancialDocument

log = logging.getLogger(__name__)
logging.getLogger("pypdf").setLevel(logging.ERROR)  # font-encoding chatter on annual reports

MAX_PDF_BYTES = 40 * 1024 * 1024


def fetch_pdf(db: Session, company_id: int, url: str, doc_type: str, title: str,
              period: str | None = None) -> tuple[FinancialDocument, bytes]:
    doc = db.scalar(select(FinancialDocument).where(FinancialDocument.company_id == company_id,
                                                    FinancialDocument.source_url == url))
    if doc and doc.local_path and Path(doc.local_path).exists():
        return doc, Path(doc.local_path).read_bytes()

    r = httpx.get(url, headers={"User-Agent": settings.nse_user_agent}, timeout=120, follow_redirects=True)
    r.raise_for_status()
    data = r.content
    if not data.startswith(b"%PDF"):
        raise ValueError(f"not a PDF: {url}")
    if len(data) > MAX_PDF_BYTES:
        raise ValueError(f"PDF too large ({len(data) // 1_000_000} MB)")
    digest = hashlib.sha256(data).hexdigest()
    path = Path(settings.docs_dir) / f"{digest[:20]}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)

    if doc is None:
        doc = FinancialDocument(company_id=company_id, source_url=url, doc_type=doc_type, title=title)
        db.add(doc)
    doc.period = period or doc.period
    doc.local_path, doc.content_hash = str(path), digest
    doc.status, doc.processed_at = "downloaded", datetime.now(timezone.utc)
    db.commit()
    return doc, data


def page_texts(data: bytes) -> list[str]:
    reader = pypdf.PdfReader(io.BytesIO(data))
    out = []
    for page in reader.pages:
        try:
            out.append(page.extract_text() or "")
        except Exception:  # damaged page; the model still sees the image
            out.append("")
    return out


def subset_pdf(data: bytes, pages: list[int]) -> bytes:
    """pages are 0-based indexes into the original document."""
    reader = pypdf.PdfReader(io.BytesIO(data))
    writer = pypdf.PdfWriter()
    for i in pages:
        writer.add_page(reader.pages[i])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()
