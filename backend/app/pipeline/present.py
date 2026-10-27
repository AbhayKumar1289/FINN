"""Deterministic wording for cards: label, headline, one-line summary, why it matters.
Chunk 3's LLM enriches only high-priority items (results numbers, appointee bios)."""
import re

from app.pipeline.classify import Classification

CATEGORY_LABEL = {
    "results": "Results", "m_and_a": "M&A", "fund_raise": "Fund raise",
    "management_change": "Management change", "litigation": "Legal / regulatory",
    "insider_trading": "Insider trade", "earnings_call": "Earnings call",
    "investor_meetings": "Investor meeting", "credit_rating": "Credit rating",
    "dividend": "Dividend", "bonus_split": "Bonus / split", "capex": "Capex",
    "press_release": "Press release", "postal_ballot": "Postal ballot", "agm_egm": "AGM / EGM",
    "pledging": "Promoter pledge", "unclassified": "Routine",
}

SUBTYPE_LABEL = {
    ("results", "filing"): "Results filing", ("results", "press_release"): "Results press release",
    ("results", "presentation"): "Results presentation", ("results", "intimation"): "Results date set",
    ("results", "newspaper_ad"): "Results newspaper ad",
    ("press_release", "order_win"): "Order win", ("press_release", "clarification"): "Clarification",
    ("m_and_a", "subsidiary"): "New subsidiary",
    ("earnings_call", "transcript"): "Call transcript", ("earnings_call", "recording"): "Call recording",
    ("earnings_call", "notice"): "Call scheduled",
    ("fund_raise", "buyback"): "Buyback", ("fund_raise", "intimation"): "Fund raise proposal",
    ("dividend", "intimation"): "Dividend proposal", ("dividend", "record_date"): "Dividend record date",
    ("bonus_split", "intimation"): "Bonus / split proposal",
    ("unclassified", "esop"): "ESOP allotment", ("unclassified", "compliance"): "Compliance filing",
    ("unclassified", "trading_window"): "Trading window", ("unclassified", "allotment"): "Share allotment",
    ("unclassified", "secretarial"): "Secretarial change", ("unclassified", "newspaper"): "Newspaper notice",
    ("unclassified", "board_meeting"): "Board meeting notice",
    ("unclassified", "board_outcome"): "Board meeting outcome", ("unclassified", "nav"): "NAV",
    ("unclassified", "other"): "Other filing",
}

WHY = {
    ("results", "filing"): "Fresh quarterly numbers; this resets the earnings picture for the stock.",
    ("results", "press_release"): "Management's framing of the quarter; the filing has the numbers.",
    ("results", "presentation"): "Management's results deck: segment detail and KPIs in their words.",
    ("results", "intimation"): "Results date fixed; expect numbers on the board meeting day.",
    ("management_change", "senior"): "A change at the top can shift strategy and execution; check who is coming in.",
    ("management_change", "board"): "Board composition change; matters more if it signals a governance shift.",
    ("m_and_a", "transaction"): "Changes what the company owns; watch the price paid and how it is funded.",
    ("m_and_a", "subsidiary"): "New legal entity; structural unless meaningful capital is committed.",
    ("fund_raise", "raise"): "New equity dilutes existing holders; new debt adds leverage.",
    ("fund_raise", "buyback"): "Cash returned by buying back shares; usually supportive of the price.",
    ("fund_raise", "intimation"): "Board will consider raising money; size and instrument decide dilution.",
    ("credit_rating", "downgrade"): "Lenders see more risk; borrowing costs may rise.",
    ("credit_rating", "upgrade"): "Lenders see less risk; funding gets cheaper.",
    ("credit_rating", "watch"): "Rating under watch; a change may follow.",
    ("credit_rating", "reaffirmed"): "Rating unchanged; no new information on credit risk.",
    ("press_release", "order_win"): "Adds to the order book; size relative to annual revenue decides if it matters.",
    ("press_release", "clarification"): "Company responding to market chatter or unusual price moves.",
    ("litigation", "action"): "Legal or regulatory exposure; the amount at stake vs. profits is what matters.",
    ("litigation", "insolvency"): "Insolvency proceeding; check whether the company is creditor or debtor.",
    ("pledging", "pledge"): "Promoter using shares as loan collateral; rising pledges are a risk flag.",
    ("bonus_split", "corporate_action"): "Share count changes; no cash value is created.",
    ("dividend", "declared"): "Cash payout to shareholders; check the record date.",
    ("capex", "capex"): "Capacity spend: growth later if demand holds, cash outflow now.",
    ("earnings_call", "transcript"): "Management's own commentary is out; feeds guidance tracking.",
    ("insider_trading", "disclosure"): "An insider changed their personal holding.",
}

PERIOD = re.compile(r"(quarter(?: and (?:half[- ]year|nine months|year))?|half[- ]year|year|period)\s+ended\s+"
                    r"(?:on\s+)?([A-Z][a-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}(?:st|nd|rd|th)?\s+[A-Z][a-z]+,?\s+\d{4})",
                    re.I)
_PREFIX = re.compile(r"^.*?\bhas\s+(?:informed|submitted to)\s+the\s+Exchange,?\s*"
                     r"(?:about|regarding|that|on)?\s*", re.I | re.S)
_REG30 = re.compile(r"^disclosure under regulation 30\b.*?regulations,?\s*2015\s*[-–:]\s*", re.I | re.S)


def label(cls: Classification) -> str:
    return SUBTYPE_LABEL.get((cls.category, cls.subtype), CATEGORY_LABEL.get(cls.category, "Filing"))


def headline(cls: Classification, text: str) -> str:
    if cls.category == "results" and cls.subtype in ("filing", "press_release"):
        m = PERIOD.search(text or "")
        if m:
            return f"Results: {m.group(1).lower()} ended {m.group(2)}"
    if cls.category == "management_change":
        role = cls.details.get("role") or "Management"
        direction = {"exit": "exit", "appointment": "appointment"}.get(cls.details.get("direction"), "change")
        return f"{role} {direction}"
    if cls.category == "credit_rating":
        return f"Credit rating {cls.subtype}"
    return label(cls)


def clean_summary(text: str, limit: int = 280) -> str:
    s = _PREFIX.sub("", (text or "").strip()).strip()
    s = _REG30.sub("", s).strip().strip("'\"").strip()
    s = re.sub(r"\s+", " ", s)
    if s:
        s = s[0].upper() + s[1:]
    return s if len(s) <= limit else s[:limit - 1].rstrip() + "…"


def why_it_matters(cls: Classification) -> str | None:
    return WHY.get((cls.category, cls.subtype))
