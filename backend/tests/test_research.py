from datetime import date

import pytest
from sqlalchemy import select

from app.ingest.screener import call_period, month_label_to_date, parse_page, sync_company
from app.llm.client import LLMResult
from app.models import Company, DocumentChunk, FinancialDocument, FinancialMetric, ManagementGuidance
from app.research import qa as qa_mod
from app.research.delivery import guidance_table, measure
from app.research.guidance import guidance_pages, locate_quote, normalise_period, period_context
from app.research.index import chunk_pages, fts_query, search

from tests.conftest import FIXTURES


def lt(db):
    return db.scalar(select(Company).where(Company.nse_symbol == "LT"))


# ---------- screener ----------
def test_parse_real_screener_page():
    page = parse_page((FIXTURES / "screener_lt.html").read_text(encoding="utf-8"), "consolidated")
    assert len(page.transcripts) >= 8 and page.transcripts[0]["url"].endswith(".pdf")
    assert page.annual_reports and page.annual_reports[0]["year"] >= 2025
    q1fy27 = page.quarters[date(2026, 6, 30)]
    assert q1fy27["revenue"] == 67942 and {"operating_profit", "pbt", "pat"} <= set(q1fy27)


def test_sync_stores_docs_and_never_overrides_filing_numbers(db):
    company = lt(db)
    db.add(FinancialMetric(company_id=company.id, metric="revenue", period="Q1FY27", value_cr=67941.74,
                           basis="consolidated", source_location="results filing p.11"))
    db.commit()
    page = parse_page((FIXTURES / "screener_lt.html").read_text(encoding="utf-8"), "consolidated")
    assert sync_company(db, company, page)["status"] == "ok"
    rev = db.scalar(select(FinancialMetric).where(FinancialMetric.company_id == company.id,
                                                  FinancialMetric.metric == "revenue",
                                                  FinancialMetric.period == "Q1FY27"))
    assert rev.value_cr == 67941.74 and rev.source_location == "results filing p.11"
    docs = db.scalars(select(FinancialDocument).where(FinancialDocument.company_id == company.id)).all()
    assert {"concall_transcript", "annual_report"} <= {d.doc_type for d in docs}


@pytest.mark.parametrize("call,period", [("Jul 2026", "Q1FY27"), ("Oct 2025", "Q2FY26"),
                                         ("Jan 2026", "Q3FY26"), ("May 2026", "Q4FY26")])
def test_call_month_to_quarter_discussed(call, period):
    assert call_period(month_label_to_date(call)) == period


def test_period_language():
    assert normalise_period("FY '27") == "FY27" and normalise_period("FY2027") == "FY27"
    assert normalise_period("H2 FY27") == "H2FY27" and normalise_period("medium term") is None
    assert "'This year' / 'current year' means FY27" in period_context("Q1FY27")
    assert "means FY27" in period_context("Q4FY26")  # Q4 call: the new year has started


# ---------- index ----------
def test_chunks_keep_page_numbers():
    pages = ["short", "A" * 50 + ". " + "word " * 600, "Revenue guidance remains 10% to 12%. " * 3]
    chunks = chunk_pages(pages)
    assert {p for p, _ in chunks} == {2, 3}
    assert all(len(t) <= 1500 for _, t in chunks)


def test_fts_search_is_company_scoped(db):
    company = lt(db)
    other = db.scalar(select(Company).where(Company.nse_symbol == "TCS"))
    from sqlalchemy import text
    for c, body in ((company, "Middle East order pipeline remains healthy"), (other, "Middle East deals")):
        d = FinancialDocument(company_id=c.id, doc_type="concall_transcript", title="call", source_url=f"u{c.id}",
                              status="indexed")
        db.add(d)
        db.flush()
        ch = DocumentChunk(document_id=d.id, chunk_index=0, text=body, page_number=3)
        db.add(ch)
        db.flush()
        db.execute(text("INSERT INTO chunk_fts(rowid, text) VALUES (:i, :t)"), {"i": ch.id, "t": body})
    db.commit()
    hits = search(db, company.id, "What is the Middle East pipeline?")
    assert len(hits) == 1 and hits[0]["page"] == 3 and "healthy" in hits[0]["text"]
    assert fts_query("what is the outlook?") == '"outlook"'


# ---------- guidance ----------
def test_guidance_pages_and_quote_verification():
    texts = ["Good evening everyone, welcome.", "We expect revenue growth of 10% to 12% for FY27 and margin "
             "guidance remains at 8.5%.", "Questions on working capital"]
    assert guidance_pages(texts) == [1]  # 0-based; greetings and Q&A filler skipped
    assert locate_quote("we expect revenue growth of 10% to 12% for FY27", texts) == 2
    assert locate_quote("we expect revenue to double next year with strong margins", texts) is None


def series_fy26_fy27():
    # FY25 quarters 100 each; FY26 111.8 each (+11.8%); Q1-Q2 FY27 124.5 (+11.4%)
    s = {(25, q): {"revenue": 100.0, "operating_profit": 12.0, "pat": 6.0} for q in range(1, 5)}
    s |= {(26, q): {"revenue": 111.8, "operating_profit": 14.0, "pat": 6.6} for q in range(1, 5)}
    s |= {(27, q): {"revenue": 124.55, "operating_profit": 15.0, "pat": 7.0} for q in (1, 2)}
    return s


def g(**kw):
    base = dict(statement="x", guidance_type="explicit_numeric", target_unit="pct", scope="company",
                metric="revenue_growth", target_low=15, target_high=None, target_period="FY26")
    return ManagementGuidance(**(base | kw))


def test_full_year_miss_and_in_progress_tracking():
    s = series_fy26_fy27()
    m = measure(g(), s)
    assert (m["status"], m["actual"], m["measured_over"]) == ("missed", 11.8, "FY26")
    m = measure(g(target_low=10, target_high=12, target_period="FY27"), s)
    assert (m["status"], m["actual"], m["measured_over"], m["partial"]) == ("on_track", 11.4, "Q1+Q2FY27", True)
    assert measure(g(target_period="FY28"), s)["status"] == "pending"


def test_segment_margin_is_never_scored_against_group():
    m = measure(g(metric="ebitda_margin", target_low=8.5, scope="segment",
                  segment="Projects & Manufacturing"), series_fy26_fy27())
    assert m["status"] == "not_comparable" and "segment" in m["reason"]
    m = measure(g(metric="ebitda_margin", target_low=12.0), series_fy26_fy27())
    assert m["status"] == "exceeded" and m["actual"] == 12.5  # 56 / 447.2 company-level


def test_qualitative_and_unmeasurable_guidance():
    s = series_fy26_fy27()
    assert measure(g(guidance_type="qualitative", target_low=None), s)["status"] == "not_comparable"
    assert measure(g(metric="order_inflow_growth"), s)["status"] == "not_comparable"
    assert measure(g(target_period=None), s)["status"] == "not_comparable"


def test_guidance_table_from_db(db):
    company = lt(db)
    for (fy, q), vals in series_fy26_fy27().items():
        for metric, v in vals.items():
            db.add(FinancialMetric(company_id=company.id, metric=metric, period=f"Q{q}FY{fy}", value_cr=v,
                                   basis="consolidated"))
    doc = FinancialDocument(company_id=company.id, doc_type="concall_transcript", title="Concall, Oct 2025",
                            source_url="u", period="Q2FY26", published_on=date(2025, 10, 1),
                            status="guidance_extracted")
    db.add(doc)
    db.flush()
    db.add(g(company_id=company.id, source_document_id=doc.id, stated_in_period="Q2FY26",
             statement="We maintain our full year revenue growth guidance at 15%.", source_location="p.4"))
    db.commit()
    t = guidance_table(db, company.id)
    row = t["rows"][0]
    assert row["status"] == "missed" and row["target"] == "15%" and row["source"]["page"] == "p.4"
    assert t["counts"] == {"missed": 1} and t["calls"][0]["period"] == "Q2FY26"


# ---------- Q&A ----------
def test_ask_without_documents_says_so(db):
    r = qa_mod.ask(db, lt(db), "What is the order outlook?")
    assert r["found"] is False and r["sources"] == []


def test_ask_cites_only_real_excerpts_and_caches(db, monkeypatch):
    hits = [{"chunk_id": 1, "text": "Order pipeline is healthy.", "page": 4, "document_id": 1,
             "title": "Concall transcript, Jul 2026", "doc_type": "concall_transcript", "period": "Q1FY27",
             "url": "u"}]
    monkeypatch.setattr(qa_mod, "search", lambda *a, **k: hits)
    calls = []

    def fake_generate(db_, task, parts, **kw):
        calls.append(parts)
        return LLMResult({"found": True, "answer": "Healthy [1] [7]", "citations": [1, 7]}, "m", False)
    monkeypatch.setattr(qa_mod, "generate", fake_generate)
    r = qa_mod.ask(db, lt(db), "Order outlook?")
    assert r["found"] and [s["n"] for s in r["sources"]] == [1]  # [7] doesn't exist: dropped
    again = qa_mod.ask(db, lt(db), "Order outlook?")
    assert again["cached"] and len(calls) == 1
