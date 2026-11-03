"""Financial snapshot, trajectory, balance sheet and cash quality from the annual statements.

Everything here is arithmetic on screener's compilation of the annual filings, done in code,
including the one-line reads ("profits turn into cash"). No model is involved: these are the
sections an analyst checks first, and they must be reproducible to the rupee."""
import re

from app.finance.calc import margin

YEARS = 6  # five years of change needs six year-ends


def inr(v: float) -> str:
    """₹ crore with Indian digit grouping: 3099638 -> '₹30,99,638 cr'."""
    n = f"{abs(round(v)):d}"
    head, tail = n[:-3], n[-3:]
    head = ",".join(re.findall(r"\d{1,2}(?=(?:\d{2})*$)", head)) if head else ""
    return f"{'-' if v < 0 else ''}₹{head + ',' if head else ''}{tail} cr"


def fy_label(period: str) -> str:
    """'Mar 2026' -> 'FY26'; other year-ends keep their month ('Dec 2025' -> "Dec '25")."""
    m = re.match(r"([A-Za-z]{3})\w*\s+(\d{4})", period)
    if not m:
        return period
    return f"FY{m.group(2)[2:]}" if m.group(1).lower() == "mar" else f"{m.group(1)} '{m.group(2)[2:]}"


def _row(table: dict | None, *names: str) -> list | None:
    """First row whose label starts with any of the names (screener varies labels by sector)."""
    if not table:
        return None
    for n in names:
        for label, vals in table["rows"].items():
            if label.startswith(n):
                return vals
    return None


def _annual(table: dict | None, *names: str) -> dict:
    """{period label: value} for year-end columns only (no TTM, no half-year balance sheet)."""
    vals = _row(table, *names)
    if not vals:
        return {}
    out = {}
    for p, v in zip(table["periods"], vals):
        if v is not None and re.match(r"[A-Za-z]{3}\w*\s+\d{4}$", p) and not p.lower().startswith("sep"):
            out[fy_label(p)] = v
    return out


def _cagr(first: float | None, last: float | None, years: int) -> float | None:
    if not first or not last or first <= 0 or last <= 0 or years <= 0:
        return None
    return round(((last / first) ** (1 / years) - 1) * 100, 1)


def _ratio(a, b, digits=2):
    return round(a / b, digits) if a is not None and b not in (None, 0) else None


def _span(series: dict) -> list[str]:
    return list(series)[-YEARS:]


def analyse(tables: dict, financial: bool = False) -> dict:
    pl, bs, cf, ra = (tables.get(k) for k in ("profit-loss", "balance-sheet", "cash-flow", "ratios"))
    revenue = _annual(pl, "sales", "revenue")
    op = _annual(pl, "operating profit", "financing profit")
    pat = _annual(pl, "net profit")
    interest = _annual(pl, "interest")
    pbt = _annual(pl, "profit before tax")
    years = _span(revenue)
    out: dict = {"years": years}

    # ---------- financial snapshot: trailing twelve months + latest year-end ----------
    ttm = {}
    if pl and pl["periods"] and pl["periods"][-1].upper() == "TTM":
        for key, names in (("revenue", ("sales", "revenue")), ("op", ("operating profit", "financing profit")),
                           ("pat", ("net profit",))):
            vals = _row(pl, *names)
            ttm[key] = vals[-1] if vals else None
    last = years[-1] if years else None
    net_worth = {y: (_annual(bs, "equity capital").get(y) or 0) + v for y, v in _annual(bs, "reserves").items()}
    debt = _annual(bs, "borrowing")
    roce = _annual(ra, "roce", "roe")
    snap = []
    if ttm.get("revenue") is not None:
        snap.append({"label": f"{'Total income' if financial else 'Revenue'}, last 12 months",
                     "value": ttm["revenue"], "unit": "cr"})
        if not financial:
            snap.append({"label": "Operating margin, last 12 months", "value": margin(ttm.get("op"), ttm["revenue"]),
                         "unit": "pct"})
        snap.append({"label": "Net profit, last 12 months", "value": ttm.get("pat"), "unit": "cr"})
        snap.append({"label": "Net margin, last 12 months", "value": margin(ttm.get("pat"), ttm["revenue"]), "unit": "pct"})
    if last and roce.get(last) is not None:
        snap.append({"label": f"{'ROE' if _row(ra, 'roe') and not _row(ra, 'roce') else 'ROCE'}, {last}",
                     "value": roce[last], "unit": "pct"})
    if last and not financial and net_worth.get(last):
        snap.append({"label": f"Debt to equity, {last}", "value": _ratio(debt.get(last, 0), net_worth[last]), "unit": "x"})
    out["snapshot"] = [{**s, "value": round(s["value"], 2 if s["unit"] == "x" else 1)} for s in snap if s["value"] is not None]

    # ---------- trajectory: what's growing, what's compressing ----------
    traj: dict = {"revenue": [revenue.get(y) for y in years], "pat": [pat.get(y) for y in years],
                  "margin": [None if (m := margin(op.get(y), revenue.get(y))) is None else round(m, 1) for y in years]
                  if not financial else None,
                  "notes": []}
    if len(years) >= 2:
        n = len(years) - 1
        rc, pc = _cagr(revenue.get(years[0]), revenue.get(last), n), _cagr(pat.get(years[0]), pat.get(last), n)
        traj["cagr"] = {"revenue": rc, "pat": pc, "from": years[0], "to": last}
        if rc is not None:
            traj["notes"].append(f"Revenue compounded {rc:.1f}% a year, {years[0]} to {last}.")
        if rc is not None and pc is not None:
            gap = pc - rc
            traj["notes"].append(
                f"Profit grew {'faster' if gap > 0 else 'slower'} than revenue ({pc:.1f}% a year): "
                + ("margins widened." if gap > 1 else "margins narrowed." if gap < -1 else "broadly in step."))
        if traj["margin"] and traj["margin"][0] is not None and traj["margin"][-1] is not None:
            d = traj["margin"][-1] - traj["margin"][0]
            peak = max((m, y) for m, y in zip(traj["margin"], years) if m is not None)
            word = "expanded" if d > 1 else "compressed" if d < -1 else "held"
            traj["notes"].append(f"Operating margin {word}: {traj['margin'][0]:.1f}% in {years[0]} to "
                                 f"{traj['margin'][-1]:.1f}% in {last}"
                                 + (f", below its {peak[0]:.1f}% peak in {peak[1]}." if peak[1] not in (years[0], last)
                                    and peak[0] - traj['margin'][-1] > 1 else "."))
        falls = [y for i, y in enumerate(years[1:], 1) if revenue.get(y) and revenue.get(years[i - 1])
                 and revenue[y] < revenue[years[i - 1]]]
        if falls:
            traj["notes"].append(f"Revenue fell year on year in {', '.join(falls)}.")
        # a one-year jump this size is usually a merger or acquisition, which flatters the growth rate
        jumps = [(y, revenue[y] / revenue[years[i - 1]] - 1) for i, y in enumerate(years[1:], 1)
                 if revenue.get(y) and revenue.get(years[i - 1]) and revenue[y] > revenue[years[i - 1]] * 1.4]
        for y, g in jumps:
            traj["notes"].append(f"Revenue jumped {g * 100:.0f}% in {y}, beyond what organic growth usually "
                                 "delivers: check for a merger or acquisition before reading the growth rate.")
    out["trajectory"] = traj

    # ---------- balance sheet ----------
    bal: dict = {"years": [y for y in years if y in net_worth], "notes": []}
    bal["net_worth"] = [net_worth.get(y) for y in bal["years"]]
    bal["debt"] = [debt.get(y) for y in bal["years"]]
    if financial:
        deposits = _annual(bs, "deposits")
        bal["deposits"] = [deposits.get(y) for y in bal["years"]]
        if last and deposits.get(last) and net_worth.get(last):
            bal["notes"].append(f"Funded mainly by deposits: {inr(deposits[last])} against net worth of "
                                f"{inr(net_worth[last])} ({deposits[last] / net_worth[last]:.1f}×) in {last}.")
        bal["notes"].append("Leverage and working-capital ratios don't apply to a lender the way they do to "
                            "a manufacturer; capital adequacy (in the annual report) is the measure that matters.")
    else:
        de = [_ratio(debt.get(y, 0), net_worth.get(y)) for y in bal["years"]]
        bal["de"] = de
        if last and net_worth.get(last):
            dl = debt.get(last, 0)
            if de[-1] is not None:
                level = ("debt-free in practice" if de[-1] < 0.1 else "lightly geared" if de[-1] < 0.5
                         else "moderately geared" if de[-1] < 1 else "borrowings exceed net worth")
                bal["notes"].append(f"{level.capitalize()}: borrowings {inr(dl)} against net worth "
                                    f"{inr(net_worth[last])} ({de[-1]:.2f}×) in {last}"
                                    + (". This is the consolidated figure: a group lending arm's borrowings "
                                       "count here too." if de[-1] >= 1 else "."))
            first = bal["years"][0]
            if debt.get(first) is not None and dl > (debt.get(first) or 0) * 1.5 and dl - (debt.get(first) or 0) > 500:
                bal["notes"].append(f"Borrowings have risen from {inr(debt[first])} in {first}.")
        if last and interest.get(last) and pbt.get(last) is not None:
            cover = (pbt[last] + interest[last]) / interest[last]
            bal["interest_cover"] = round(cover, 1)
            bal["notes"].append(f"Interest cover {cover:.0f}×: operating earnings pay interest "
                                + ("many times over." if cover > 10 else "comfortably." if cover >= 4
                                   else "adequately." if cover >= 2 else "with little room."))
        wc, ccc = _annual(ra, "working capital days"), _annual(ra, "cash conversion cycle")
        bal["wc_days"] = [wc.get(y) for y in bal["years"]]
        bal["ccc"] = [ccc.get(y) for y in bal["years"]]
        if last and ccc.get(last) is not None and ccc.get(bal["years"][0]) is not None:
            d = ccc[last] - ccc[bal["years"][0]]
            neg = (" (negative: customer advances and suppliers fund day-to-day operations)"
                   if ccc[last] < 0 else "")
            bal["notes"].append(f"Cash conversion cycle {ccc[last]:.0f} days in {last}{neg}"
                                + (f", {abs(d):.0f} days {'longer' if d > 0 else 'shorter'} than in {bal['years'][0]}: "
                                   f"{'more' if d > 0 else 'less'} cash tied up in working capital." if abs(d) >= 5
                                   else ", broadly unchanged."))
    out["balance"] = bal

    # ---------- cash quality: do profits turn into cash? ----------
    cfo, fcf = _annual(cf, "cash from operating"), _annual(cf, "free cash flow")
    cy = [y for y in years if y in cfo and y in pat]
    cash: dict = {"years": cy, "cfo": [cfo[y] for y in cy], "pat": [pat[y] for y in cy],
                  "fcf": [fcf.get(y) for y in cy], "conversion": [_ratio(cfo[y], pat[y], 2) for y in cy],
                  "notes": [], "applicable": not financial}
    if financial:
        cash["notes"].append("For a lender, operating cash flow swings with deposits taken and loans made, so "
                             "cash conversion isn't a meaningful test of earnings quality.")
    elif cy:
        tc, tp = sum(cfo[y] for y in cy), sum(pat[y] for y in cy)
        ratio = tc / tp if tp > 0 else None
        cash["cumulative"] = {"cfo": tc, "pat": tp, "ratio": round(ratio, 2) if ratio else None,
                              "from": cy[0], "to": cy[-1]}
        if ratio is not None:
            read = ("profits turn into cash, and then some" if ratio >= 1.1 else "profits turn into cash"
                    if ratio >= 0.9 else "a fair share of profit is tied up (working capital or non-cash gains)"
                    if ratio >= 0.7 else "profits are not turning into cash")
            cash["notes"].append(f"Operating cash flow was {ratio:.2f}× net profit over {cy[0]}–{cy[-1]}: {read}.")
        weak = [y for y in cy if (r := _ratio(cfo[y], pat[y])) is not None and pat[y] > 0 and r < 0.7]
        if weak:
            cash["notes"].append(f"Weak conversion (below 0.7×) in {', '.join(weak)}.")
        fy = [(y, fcf[y]) for y in cy if fcf.get(y) is not None]
        if fy:
            neg = [y for y, v in fy if v < 0]
            total = sum(v for _, v in fy)
            cash["notes"].append(f"Free cash flow {inr(total)} in total over the period"
                                 + (f"; negative in {', '.join(neg)}." if neg else ", positive every year."))
    out["cash"] = cash
    return out
