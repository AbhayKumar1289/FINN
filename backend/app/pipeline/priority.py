"""Priority = what kind of filing it is + how the market reacted. 0-100, with reasons."""
from app.pipeline.classify import Classification
from app.pipeline.present import label

CATEGORY_BASE = {
    "results": 70, "m_and_a": 70, "fund_raise": 65, "litigation": 55, "management_change": 50,
    "credit_rating": 55, "pledging": 55, "capex": 55, "bonus_split": 50, "dividend": 35,
    "insider_trading": 35, "press_release": 30, "earnings_call": 30, "investor_meetings": 15,
    "agm_egm": 15, "postal_ballot": 15, "unclassified": 5,
}
SUBTYPE_BASE = {
    ("results", "filing"): 85, ("results", "press_release"): 75, ("results", "presentation"): 45,
    ("results", "intimation"): 30, ("results", "newspaper_ad"): 5,
    ("management_change", "senior"): 80, ("management_change", "board"): 45,
    ("management_change", "other"): 35,
    ("m_and_a", "subsidiary"): 40,
    ("credit_rating", "downgrade"): 80, ("credit_rating", "watch"): 60,
    ("credit_rating", "upgrade"): 60, ("credit_rating", "reaffirmed"): 20,
    ("press_release", "order_win"): 55, ("press_release", "regulatory_approval"): 60, ("press_release", "clarification"): 45,
    ("earnings_call", "transcript"): 40, ("earnings_call", "notice"): 20,
    ("fund_raise", "buyback"): 70, ("fund_raise", "intimation"): 45,
    ("dividend", "intimation"): 20, ("dividend", "record_date"): 20,
    ("bonus_split", "intimation"): 35,
}
HIGH, MEDIUM = 70, 40
REACTION_FLOOR = 20  # routine filings don't inherit a price move they didn't cause


def bucket(score: float) -> str:
    return "high" if score >= HIGH else "medium" if score >= MEDIUM else "low"


# Order size vs trailing-twelve-month revenue. L&T books orders every week; what matters is
# whether one moves the needle.
ORDER_LARGE_PCT, ORDER_SMALL_PCT = 5.0, 1.0


def score_announcement(cls: Classification, reaction: dict | None,
                       price_threshold: float, volume_threshold: float,
                       materiality: dict | None = None) -> tuple[float, list[str]]:
    base = SUBTYPE_BASE.get((cls.category, cls.subtype), CATEGORY_BASE.get(cls.category, 5))
    reasons = [label(cls)]
    pct = (materiality or {}).get("pct_of_revenue")
    if pct is not None and cls.category in ("press_release", "m_and_a", "fund_raise", "capex"):
        share = "<0.1%" if pct < 0.1 else f"{pct:.1f}%"
        if pct >= ORDER_LARGE_PCT:
            base = max(base, 75)
            reasons.append(f"Large: {share} of annual revenue")
        elif pct < ORDER_SMALL_PCT and (cls.subtype == "order_win" or cls.category == "m_and_a"):
            # a ₹1 lakh CSR foundation is not M&A news, whatever the exchange calls it
            base = min(base, 30 if cls.subtype == "order_win" else 20)
            reasons.append(f"Immaterial: {share} of annual revenue")
        else:
            reasons.append(f"{share} of annual revenue")
    score = float(base)
    if cls.details.get("role"):
        reasons.append(f"Role: {cls.details['role']}")
    if cls.details.get("also"):
        score += 5
        reasons.append("Also covers: " + ", ".join(a.replace("_", " ") for a in cls.details["also"]))

    if base >= REACTION_FLOOR and reaction:
        if reaction.get("status") == "pending":
            reasons.append("Market reaction pending (next session)")
        elif reaction.get("status") == "ok":
            chg, rvol, day = reaction.get("change_pct"), reaction.get("relative_volume"), reaction["session"]
            if chg is not None and abs(chg) >= price_threshold:
                score += 15
                reasons.append(f"Stock moved {chg:+.1f}% on {day}")
            elif chg is not None and abs(chg) >= price_threshold / 2:
                score += 5
                reasons.append(f"Stock moved {chg:+.1f}% on {day}")
            if rvol is not None and rvol >= volume_threshold:
                score += 10
                reasons.append(f"Volume {rvol:.1f}x normal on {day}")
    return min(score, 100.0), reasons
