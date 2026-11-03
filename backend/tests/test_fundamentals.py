from types import SimpleNamespace

from app.research import perspective
from app.research.fundamentals import analyse, fy_label

YRS = ["Mar 2021", "Mar 2022", "Mar 2023", "Mar 2024", "Mar 2025", "Mar 2026"]


def table(periods, rows):
    return {"periods": periods, "rows": rows}


def statements(**over):
    t = {
        "profit-loss": table(YRS + ["TTM"], {
            "sales": [100, 110, 121, 133.1, 146.4, 161.1, 170],
            "operating profit": [20, 21, 22, 22, 22, 22.5, 24],
            "interest": [2, 2, 2, 2, 2, 2, 2],
            "profit before tax": [16, 17, 18, 18, 18, 18, 20],
            "net profit": [12, 12.5, 13, 13, 13.2, 13.5, 15]}),
        "balance-sheet": table(YRS + ["Sep 2026"], {
            "equity capital": [10] * 7, "reserves": [90, 100, 110, 120, 130, 140, 150],
            "borrowings": [20, 22, 24, 26, 28, 75, 80]}),
        "cash-flow": table(YRS, {"cash from operating activity": [13, 6, 14, 14, 15, 16],
                                 "free cash flow": [8, -2, 9, 9, 10, 11]}),
        "ratios": table(YRS, {"cash conversion cycle": [40, 45, 50, 55, 60, 70], "roce %": [18, 18, 17, 16, 15, 15]}),
    }
    return t | over


def test_fy_labels():
    assert fy_label("Mar 2026") == "FY26" and fy_label("Dec 2025") == "Dec '25"


def test_snapshot_uses_ttm_and_latest_year_end():
    a = analyse(statements())
    snap = {s["label"]: s["value"] for s in a["snapshot"]}
    assert snap["Revenue, last 12 months"] == 170
    assert snap["Operating margin, last 12 months"] == 14.1
    assert snap["Debt to equity, FY26"] == 0.5  # 75 / (10 + 140); the half-year column is ignored
    assert a["years"][-1] == "FY26"


def test_trajectory_reads_are_computed():
    t = analyse(statements())["trajectory"]
    assert t["cagr"]["revenue"] == 10.0 and t["cagr"]["from"] == "FY21"
    assert any("slower than revenue" in n and "narrowed" in n for n in t["notes"])
    assert any("compressed: 20.0% in FY21 to 14.0% in FY26" in n for n in t["notes"])


def test_merger_sized_jump_is_flagged():
    st = statements()
    st["profit-loss"]["rows"]["sales"] = [100, 105, 110, 180, 190, 200, 205]
    assert any("jumped 64% in FY24" in n for n in analyse(st)["trajectory"]["notes"])


def test_balance_sheet_and_cash_quality():
    a = analyse(statements())
    b, c = a["balance"], a["cash"]
    assert b["de"][-1] == 0.5 and any(n.startswith("Moderately geared") for n in b["notes"])
    assert b["interest_cover"] == 10.0
    assert any("longer than in FY21" in n for n in b["notes"])
    assert c["cumulative"]["ratio"] == round(78 / 77.2, 2)
    assert any("FY22" in n and "Weak conversion" in n for n in c["notes"])
    assert any("negative in FY22" in n for n in c["notes"])


def test_lenders_skip_leverage_and_cash_conversion():
    st = statements()
    st["balance-sheet"]["rows"]["deposits"] = [500, 550, 600, 650, 700, 750, 760]
    a = analyse(st, financial=True)
    assert "de" not in a["balance"] and a["cash"]["applicable"] is False
    assert all("Operating margin" not in s["label"] for s in a["snapshot"])
    assert any("deposits" in n for n in a["balance"]["notes"])


def test_bull_bear_drops_uncited_points(monkeypatch):
    monkeypatch.setattr(perspective, "search", lambda *a, **k: [])
    monkeypatch.setattr(perspective, "generate", lambda *a, **k: SimpleNamespace(model="m", data={
        "bull": [{"point": "Cash-rich [1].", "refs": [1]}, {"point": "Vibes.", "refs": []}],
        "bear": [{"point": "Margins fell.", "refs": [2, 99]}]}))
    out = perspective.bull_bear(None, SimpleNamespace(id=1, name="X"), ["fact one", "fact two", "fact three"], [])
    assert [p["point"] for p in out["bull"]] == ["Cash-rich."]  # uncited dropped, marker stripped
    assert out["bear"][0]["refs"] == [2]  # out-of-range citation removed
    assert {s["n"] for s in out["sources"]} == {1, 2}
