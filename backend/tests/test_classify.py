import pytest

from app.pipeline.classify import classify
from app.pipeline.present import clean_summary, headline
from app.pipeline.priority import bucket, score_announcement

# (subject, description, category, subtype) - the first nine are verbatim NSE filings.
CASES = [
    ("Outcome of Board Meeting",
     "Larsen & Toubro Limited has submitted to the Exchange, the consolidated and standalone "
     "un-audited financial results of the Company for the quarter and half-year ended September 30, 2026.",
     "results", "filing"),
    ("Press Release",
     'Maruti Suzuki India Limited has informed the Exchange regarding a press release dated October 27, '
     '2026, titled "Maruti Suzuki India Limited Financial Results Q2 and H1 FY 2026-27".',
     "results", "press_release"),
    ("General Updates",
     "HDFC Bank Limited has informed the Exchange regarding disclosure under Regulation 30 - Change in "
     "Managing Director and Chief Executive Officer of the Bank",
     "management_change", "senior"),
    ("Bagging/Receiving of orders/contracts",
     "Larsen & Toubro Limited has informed the Exchange about Bagging/Receiving of orders/contracts",
     "press_release", "order_win"),
    ("Allotment of Securities",
     "Larsen & Toubro Limited has informed the Exchange regarding allotment of 21098 securities "
     "pursuant to ESOP/ESPS", "unclassified", "esop"),
    ("Alteration Of Capital and Fund Raising-XBRL",
     "ICICI BANK LIMITED has informed the Exchange regarding Allotment of Securities",
     "unclassified", "allotment"),
    ("Acquisition",
     "Maruti Suzuki India Limited has informed the Exchange about Incorporation of Wholly Owned Subsidiary",
     "m_and_a", "subsidiary"),
    ("Analysts/Institutional Investor Meet/Con. Call Updates",
     "UltraTech Cement Limited has informed the Exchange about Transcript", "earnings_call", "transcript"),
    ("Record Date Updates", "Record Date Updates", "unclassified", "compliance"),
    # constructed cases for paths today's feed didn't exercise
    ("Board Meeting Intimation",
     "X Limited has informed the Exchange about Board Meeting to be held on 5-Nov-2026 to consider "
     "and approve the financial results for the quarter ended September 30, 2026",
     "results", "intimation"),
    ("Board Meeting Intimation",
     "X Limited has informed the Exchange about Board Meeting to consider fund raising by way of QIP",
     "fund_raise", "intimation"),
    ("Credit Rating", "CRISIL has downgraded the long-term rating of the company to AA-",
     "credit_rating", "downgrade"),
    ("Credit Rating", "ICRA has reaffirmed the rating at AAA (Stable)", "credit_rating", "reaffirmed"),
    ("Change in Directors/KMP/SMP/Auditor/RTA",
     "Appointment of M/s ABC & Co. as Secretarial Auditor", "unclassified", "secretarial"),
    ("Change in Directors/KMP/SMP/Auditor/RTA",
     "Resignation of Mr. A as Chief Financial Officer", "management_change", "senior"),
    ("Change in Directors/KMP/SMP/Auditor/RTA",
     "Appointment of Ms. B as Independent Director", "management_change", "board"),
    ("Updates", "Infosys Limited has informed the Exchange regarding 'Infosys Successfully Delivers "
                "Syngenta s Global SAP S/4HANA Transformation'", "press_release", "general"),
    ("Updates", "Company has received a show cause notice from the GST department", "litigation", "action"),
    ("Declaration of NAV", "NAV of the scheme", "unclassified", "nav"),
    ("Disclosure under SEBI Takeover Regulations", "Substantial Acquisition of Shares and Takeovers",
     "insider_trading", "disclosure"),
]


@pytest.mark.parametrize("subject,text,category,subtype", CASES)
def test_classification(subject, text, category, subtype):
    c = classify(subject, text)
    assert (c.category, c.subtype) == (category, subtype), c.rule


def test_md_and_ceo_is_one_role():
    c = classify("General Updates", "Change in Managing Director and Chief Executive Officer of the Bank")
    assert c.details["role"] == "MD & CEO"
    assert headline(c, "") == "MD & CEO change"


def test_exit_direction():
    c = classify("Change in Directors/KMP/SMP/Auditor/RTA", "Resignation of Mr. A as Chief Financial Officer")
    assert c.details["direction"] == "exit" and headline(c, "") == "CFO exit"


def test_secondary_signals_are_kept():
    c = classify("Outcome of Board Meeting",
                 "The Board approved the audited financial results for the year ended March 31, 2026, "
                 "recommended a final dividend and approved appointment of Mr. X as Independent Director")
    assert c.category == "results"
    assert {"dividend", "management_change"} <= set(c.details["also"])


def test_results_headline_uses_period():
    text = "the financial results for the period ended September 30, 2026."
    assert headline(classify("Outcome of Board Meeting", text), text) == \
        "Results: period ended September 30, 2026"


def test_clean_summary_strips_boilerplate():
    s = clean_summary("Infosys Limited has informed the Exchange regarding 'Infosys wins award'")
    assert s == "Infosys wins award"
    s = clean_summary("HDFC Bank Limited has informed the Exchange regarding disclosure under Regulation 30 "
                      "and other applicable regulations of the SEBI (Listing Obligations and Disclosure "
                      "Requirements) Regulations, 2015 - Change in Managing Director and Chief Executive Officer")
    assert s == "Change in Managing Director and Chief Executive Officer"


def test_priority_buckets_and_reaction_boost():
    results = classify("Outcome of Board Meeting", "un-audited financial results for the quarter")
    esop = classify("ESOP/ESOS/ESPS", "Allotment of shares")
    calm = {"status": "ok", "session": "2026-10-27", "change_pct": 0.4, "relative_volume": 1.0}
    hot = {"status": "ok", "session": "2026-10-27", "change_pct": -7.2, "relative_volume": 3.1}
    assert bucket(score_announcement(results, calm, 5, 2)[0]) == "high"
    assert bucket(score_announcement(esop, calm, 5, 2)[0]) == "low"
    score, reasons = score_announcement(results, hot, 5, 2)
    assert score == 100 and any("-7.2%" in r for r in reasons) and any("3.1x" in r for r in reasons)
    # a routine filing doesn't borrow a move it didn't cause
    assert score_announcement(esop, hot, 5, 2)[0] == 5
    _, reasons = score_announcement(results, {"status": "pending"}, 5, 2)
    assert "Market reaction pending (next session)" in reasons
