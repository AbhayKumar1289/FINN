"""AI-layer tests. No network: model responses are real transcriptions saved from the
27 Oct 2026 L&T and Maruti filings, or stubs."""
import json
from datetime import date

import pytest
from sqlalchemy import func, select

from app.extract import enrich as enrich_mod
from app.extract import people as people_mod
from app.extract import results as results_mod
from app.extract.results import (build_results, candidate_pages, fiscal_quarter, months_back,
                                 parse_unit, results_line, results_verdict, rows_to_periods)
from app.llm import client
from app.llm.client import LLMResult, generate
from app.models import Announcement, Company, LLMCall

from tests.conftest import FIXTURES

RAW = json.loads((FIXTURES / "results_transcriptions.json").read_text(encoding="utf-8"))


# ---------- deterministic helpers ----------
def test_fiscal_quarters():
    assert fiscal_quarter(date(2026, 9, 30)) == "Q2FY27"
    assert fiscal_quarter(date(2026, 3, 31)) == "Q4FY26"
    assert fiscal_quarter(date(2025, 12, 31)) == "Q3FY26"
    with pytest.raises(ValueError):
        fiscal_quarter(date(2026, 8, 31))
    assert months_back(date(2026, 9, 30), 3) == date(2026, 6, 30)
    assert months_back(date(2026, 3, 31), 3) == date(2025, 12, 31)
    assert months_back(date(2026, 9, 30), 12) == date(2025, 9, 30)


@pytest.mark.parametrize("printed,unit", [("₹ Crore", "crore"), ("INR in million", "million"),
                                          ("Rs. in Lakhs", "lakh"), ("(₹ in crore)", "crore")])
def test_units(printed, unit):
    assert parse_unit(printed) == unit


def test_total_revenue_row_beats_header_row():
    st = {"columns": [{"period_end": "2026-09-30", "period_type": "quarter"}],
          "rows": [{"label": "Revenue from operations", "values": [500]},
                   {"label": "Total revenue from operations", "values": [533]},
                   {"label": "Profit before exceptional items and tax", "values": [40]},
                   {"label": "Profit before tax", "values": [38]},
                   {"label": "Total comprehensive income for the period", "values": [99]},
                   {"label": "Profit for the period", "values": [30]}]}
    p = rows_to_periods(st)[0]
    assert p["revenue_from_operations"] == 533
    assert p["profit_before_exceptional_items_and_tax"] == 40 and p["profit_before_tax"] == 38
    assert p["net_profit"] == 30  # comprehensive income row ignored


def test_candidate_pages_prefers_pnl_tables():
    texts = ["Dear sir, please find results", "Revenue from operations Profit before tax Finance costs "
             "Depreciation Other income Total income", "Segment information", "Notes"]
    assert candidate_pages(texts, 4) == [1]
    assert candidate_pages(["", "", ""], 4) == [0, 1, 2]  # image-only scan: show the front pages


# ---------- real filings ----------
def test_lt_q2fy27_consolidated():
    r, issues = build_results(RAW["lt"], financial=False)
    assert issues == []
    assert (r["period"], r["prev_period"], r["year_ago_period"], r["basis"]) == \
        ("Q2FY27", "Q1FY27", "Q2FY26", "consolidated")
    m = r["metrics"]
    assert m["revenue"]["current_cr"] == pytest.approx(78749.94)
    assert m["revenue"]["yoy"]["value"] == pytest.approx(15.84, abs=0.01)
    assert m["pat"]["current_cr"] == pytest.approx(5202.1, abs=0.1)
    assert m["ebitda"]["current_cr"] is not None and r["margins"]["ebitda"]["current_pct"] == 8.7


def test_maruti_scanned_standalone_in_millions():
    r, issues = build_results(RAW["maruti"], financial=False)
    assert issues == [] and r["basis"] == "standalone"
    assert r["metrics"]["revenue"]["current_cr"] == pytest.approx(53340.2)   # 533,402 INR mn
    assert r["metrics"]["pbt"]["current_cr"] == pytest.approx(3165.8)
    assert results_verdict(r).startswith("Revenue grew but profit fell")
    assert results_line(r).startswith("Revenue ₹53,340 cr (+26.0% YoY")


def test_bank_has_no_ebitda():
    r, issues = build_results(RAW["lt"], financial=True)
    assert issues == [] and r["metrics"]["ebitda"]["current_cr"] is None
    assert "not meaningful" in r["notes"][0]


def test_validation_catches_missing_lines():
    raw = json.loads(json.dumps(RAW["lt"]))
    for st in raw["statements"]:
        st["rows"] = [row for row in st["rows"] if "before tax" not in row["label"].lower()]
    _, issues = build_results(raw, financial=False)
    assert "missing pbt for the current quarter" in issues
    _, issues = build_results({"statements": []}, financial=False)
    assert issues


# ---------- llm client: cache + cost ----------
def fake_response(payload: dict, tin=100, tout=20):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}],
            "usageMetadata": {"promptTokenCount": tin, "candidatesTokenCount": tout}}


def test_cache_serves_repeats_for_free(db, monkeypatch):
    calls = []
    monkeypatch.setattr(client.settings, "gemini_api_key", "test")
    monkeypatch.setattr(client, "_post", lambda model, body: calls.append(body) or fake_response({"ok": 1}))
    schema = {"type": "object", "properties": {"ok": {"type": "integer"}}}
    a = generate(db, "t", [{"text": "hi"}], schema=schema)
    b = generate(db, "t", [{"text": "hi"}], schema=schema)
    assert a.data == b.data == {"ok": 1} and not a.cached and b.cached and len(calls) == 1
    assert a.cost_usd > 0 and db.scalar(select(func.count(LLMCall.id))) == 1
    generate(db, "t", [{"text": "different"}], schema=schema)
    assert len(calls) == 2


def test_thinking_knob_falls_back_when_unsupported(db, monkeypatch):
    bodies = []

    def post(model, body):
        bodies.append(json.loads(json.dumps(body)))
        if "thinkingConfig" in body["generationConfig"]:
            raise client.LLMError("gemini x 400: thinking level is not supported")
        return fake_response({"ok": 1})
    monkeypatch.setattr(client.settings, "gemini_api_key", "test")
    monkeypatch.setattr(client, "_post", post)
    assert generate(db, "t", [{"text": "x"}], schema={"type": "object"}, thinking="low").data == {"ok": 1}
    assert len(bodies) == 2 and "thinkingConfig" not in bodies[1]["generationConfig"]


# ---------- enrichment routing ----------
def make_ann(db, symbol, category, subtype, url="https://example.test/f.pdf"):
    c = db.scalar(select(Company).where(Company.nse_symbol == symbol))
    from datetime import datetime, timezone
    ann = Announcement(company_id=c.id, source="nse", source_id=f"{symbol}-{category}", title="t",
                       published_at=datetime.now(timezone.utc).replace(tzinfo=None),
                       document_url=url, category=category, processing_status="processed",
                       priority="high", priority_score=85,
                       extracted={"classification": {"subtype": subtype}})
    db.add(ann)
    db.commit()
    return ann


def test_cheap_first_then_escalate(db, monkeypatch):
    tiers = []
    bad = {"statements": [{"basis": "consolidated", "unit": "₹ crore", "columns": [], "rows": []}]}

    def fake_generate(db_, task, parts, tier="cheap", **kw):
        tiers.append(tier)
        return LLMResult(bad if tier == "cheap" else RAW["lt"], f"model-{tier}", False, cost_usd=0.001)
    monkeypatch.setattr(results_mod, "generate", fake_generate)
    monkeypatch.setattr(results_mod, "fetch_pdf", lambda *a, **k: (type("D", (), {"id": None, "period": None,
                                                                                  "status": None})(), b"%PDF"))
    monkeypatch.setattr(results_mod, "page_texts", lambda data: ["Revenue from operations profit before tax "
                                                                 "finance costs depreciation"] * 3)
    monkeypatch.setattr(results_mod, "subset_pdf", lambda data, pages: b"%PDF-subset")
    monkeypatch.setattr(results_mod, "_store_metrics", lambda *a: None)
    monkeypatch.setattr(enrich_mod.settings, "gemini_api_key", "test")
    ann = make_ann(db, "LT", "results", "filing")
    out = enrich_mod.enrich_pending(db)
    assert out == [{"id": ann.id, "status": "ok"}] and tiers == ["cheap", "strong"]
    db.refresh(ann)
    assert ann.extracted["results"]["period"] == "Q2FY27"
    assert ann.why_it_matters.startswith("Strong quarter")
    assert enrich_mod.enrich_pending(db) == []  # done items are not re-sent


def test_only_material_filings_are_enriched(db, monkeypatch):
    monkeypatch.setattr(enrich_mod.settings, "gemini_api_key", "test")
    make_ann(db, "INFY", "press_release", "general")
    make_ann(db, "TCS", "unclassified", "esop")
    make_ann(db, "ITC", "results", "filing", url=None)
    assert enrich_mod.enrich_pending(db) == []


# ---------- people ----------
def run_people(db, monkeypatch, changes, bio=None):
    seen = []

    def fake_generate(db_, task, parts, tier="cheap", **kw):
        seen.append((task, tier))
        if task == "people_extract":
            return LLMResult({"changes": changes}, "m", False)
        return LLMResult(bio, "m", False)
    monkeypatch.setattr(people_mod, "generate", fake_generate)
    monkeypatch.setattr(people_mod, "fetch_pdf", lambda *a, **k: (None, b"%PDF"))
    monkeypatch.setattr(people_mod, "page_texts", lambda data: ["page"])
    monkeypatch.setattr(people_mod, "subset_pdf", lambda data, pages: b"%PDF")
    ann = make_ann(db, "HDFCBANK", "management_change", "senior")
    return people_mod.extract_people(db, ann), seen


def test_profile_in_filing_needs_no_lookup(db, monkeypatch):
    out, seen = run_people(db, monkeypatch, [
        {"name": "A Person", "role": "CFO", "direction": "appointment", "profile": "CA with 20 years at X."}])
    assert out["changes"][0]["background"] == {"bio": "CA with 20 years at X.", "source": "filing", "verified": True}
    assert [t for t, _ in seen] == ["people_extract"]


def test_model_bio_is_labelled_unverified(db, monkeypatch):
    out, seen = run_people(db, monkeypatch, [
        {"name": "Old Boss", "role": "MD & CEO", "direction": "exit"},
        {"name": "New Boss", "role": "MD & CEO", "direction": "appointment"}],
        bio={"known": True, "bio": "Spent 20 years at Y.", "confidence": "high"})
    bg = out["changes"][1]["background"]
    assert bg["source"] == "model_knowledge" and bg["verified"] is False and "Verify" in bg["note"]
    assert out["line"] == "New Boss takes over as MD & CEO from Old Boss"
    assert ("bio_knowledge", "strong") in seen and "background" not in out["changes"][0]


def test_unknown_person_gets_no_invented_bio(db, monkeypatch):
    out, _ = run_people(db, monkeypatch, [{"name": "Z", "role": "Director", "direction": "appointment"}],
                        bio={"known": False, "bio": None, "confidence": "low"})
    assert out["changes"][0]["background"]["bio"] is None
