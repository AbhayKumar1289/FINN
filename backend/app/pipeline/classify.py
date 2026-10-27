"""Rule-based announcement classifier. Free, instant and explainable: every result records
the rule that fired. The LLM (chunk 3) only reads the few filings that earn it.

Two passes: the exchange's own subject line is the most reliable signal, so it is checked
first; generic subjects ("Updates", "Press Release", "Outcome of Board Meeting") fall
through to keyword signals in the description."""
import re
from dataclasses import dataclass, field

# Categories from the companion reference document.
CATEGORIES = ("results", "m_and_a", "fund_raise", "management_change", "litigation",
              "insider_trading", "earnings_call", "investor_meetings", "credit_rating",
              "dividend", "bonus_split", "capex", "press_release", "postal_ballot",
              "agm_egm", "pledging", "unclassified")


@dataclass(frozen=True)
class Classification:
    category: str
    subtype: str | None
    rule: str
    details: dict = field(default_factory=dict)


def _rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.I)


# ---- description signals ----
RESULTS = _rx(r"financial results|quarterly results|(un-?audited|audited).{0,60}results"
              r"|results for the (quarter|period|year)|\bq[1-4]\b.{0,30}results")
ORDER_WIN = _rx(r"\b(bag|receiv|win|wins|won|secur|award)\w*\b.{0,60}\b(orders?|contracts?)\b"
                r"|\b(orders?|contracts?)\b.{0,40}\b(bag|receiv|won|secur|award)\w*")
SUBSIDIARY = _rx(r"incorporat\w*\s+(of\s+)?(an?\s+)?(new\s+)?(wholly[- ]owned\s+)?(step[- ]down\s+)?subsidiar")
M_AND_A = _rx(r"acqui|amalgamat|merger|demerg|scheme of arrangement|joint venture|\bjv\b"
              r"|divest|disinvest|stake sale|slump sale|sale of (stake|business|undertaking)")
MGMT = _rx(r"appoint|resign|cessation|step(s|ped)? down|re-?designat|retire|chief executive"
           r"|\bceo\b|\bcfo\b|managing director|key managerial|senior management")
FUND = _rx(r"qualified institution|\bqip\b|rights issue|preferential (issue|allotment)|fund ?rais"
           r"|commercial paper|non-convertible debenture|\bncds?\b|warrants")
BUYBACK = _rx(r"buy[- ]?back")
ESOP = _rx(r"\besop|\besos|\besps|employee stock|stock option")
RATING = _rx(r"credit rating|\b(crisil|icra|care ratings|india ratings|acuite|brickwork)\b")
LITIGATION = _rx(r"penalt|show[- ]cause|demand (order|notice)|tax demand|gst (demand|order|notice)"
                 r"|levied|search (and|&) seizure|insolvency|\bcirp\b|litigation|lawsuit|arbitra"
                 r"|order passed|actions? initiated|warning letter|import alert|form 483")
CAPEX = _rx(r"capex|capital expenditure|capacity (expansion|addition|augmentation)"
            r"|new (plant|facility|factory)|commercial (production|operations?)|commissioning"
            r"|greenfield|brownfield")
DIVIDEND = _rx(r"dividend")
BONUS_SPLIT = _rx(r"\bbonus\b|stock split|split of|sub-?division")
CLARIFICATION = _rx(r"clarification|spurt|news item|media report")
POSTAL = _rx(r"postal ballot")
INSIDER = _rx(r"insider trading|\bsast\b|substantial acquisition|regulation 7\s*\(2\)|prohibition of insider")
PLEDGE = _rx(r"pledg|encumbr")

# ---- exchange subjects that are routine by construction ----
ROUTINE_SUBJECT = _rx(r"certificate under sebi|depositories and participants|regulation 74|loss of share"
                      r"|duplicate share|security cover|redemption|payment of interest|regulation 5[0-7]"
                      r"|monitoring agency|deviation|utili[sz]ation of issue proceeds|compliance certificate"
                      r"|business responsibility|\bbrsr\b|\besg\b")

ROLES = [("MD", r"managing director|\bmd\b"), ("CEO", r"\bceo\b|chief executive"),
         ("CFO", r"\bcfo\b|chief financial"), ("Chairperson", r"chair(man|person|woman)"),
         ("Whole-time Director", r"whole[- ]time director|executive director"),
         ("Company Secretary", r"company secretary|compliance officer"), ("Auditor", r"auditor"),
         ("RTA", r"registrar|\brta\b|share transfer agent"),
         ("Independent Director", r"independent director"), ("Director", r"\bdirector"),
         ("Senior Management", r"senior management|\bsmp\b|key managerial|\bkmp\b|president"
                               r"|chief \w+ officer|head of")]
SENIOR_ROLES = {"CEO", "CFO", "MD", "Chairperson", "Whole-time Director"}
BOARD_ROLES = {"Independent Director", "Director"}
ROUTINE_ROLES = {"Company Secretary", "Auditor", "RTA"}
EXIT = _rx(r"resign|cessation|step(s|ped)? down|retire|demise")
APPOINT = _rx(r"appoint|induct|elevat|re-?designat|nominat")


def _mgmt(text: str, rule: str) -> Classification:
    found = [label for label, p in ROLES if re.search(p, text, re.I)]
    senior = [r for r in found if r in SENIOR_ROLES]
    # "Managing Director and Chief Executive Officer" is one person: "MD & CEO"
    role = " & ".join(senior[:2]) if senior else (found[0] if found else None)
    direction = "exit" if EXIT.search(text) else "appointment" if APPOINT.search(text) else None
    details = {"role": role, "direction": direction}
    if role in ROUTINE_ROLES:
        return Classification("unclassified", "secretarial", rule, details)
    sub = "senior" if senior else "board" if role in BOARD_ROLES else "other"
    return Classification("management_change", sub, rule, details)


def _rating_action(text: str) -> str:
    for sub, p in (("downgrade", r"downgrad|lowered|revised.{0,20}(downward|negative)"),
                   ("watch", r"watch|outlook.{0,20}negative"),
                   ("upgrade", r"upgrad|revised.{0,20}(upward|positive)"),
                   ("reaffirmed", r"reaffirm|re-affirm|retain|maintain"),
                   ("assigned", r"assign")):
        if re.search(p, text, re.I):
            return sub
    return "update"


def _from_text(text: str, results_subtype: str, default: Classification,
               prefix: str) -> Classification:
    """First matching description signal wins; the rest are kept as `also`."""
    signals = [
        (RESULTS, lambda: Classification("results", results_subtype, f"{prefix}:results")),
        (ORDER_WIN, lambda: Classification("press_release", "order_win", f"{prefix}:order_win")),
        (SUBSIDIARY, lambda: Classification("m_and_a", "subsidiary", f"{prefix}:subsidiary")),
        (M_AND_A, lambda: Classification("m_and_a", "transaction", f"{prefix}:m_and_a")),
        (BUYBACK, lambda: Classification("fund_raise", "buyback", f"{prefix}:buyback")),
        (FUND, lambda: Classification("fund_raise", "raise", f"{prefix}:fund_raise")),
        (MGMT, lambda: _mgmt(text, f"{prefix}:management")),
        (RATING, lambda: Classification("credit_rating", _rating_action(text), f"{prefix}:rating")),
        (LITIGATION, lambda: Classification("litigation", "action", f"{prefix}:litigation")),
        (CAPEX, lambda: Classification("capex", "capex", f"{prefix}:capex")),
        (BONUS_SPLIT, lambda: Classification("bonus_split", "corporate_action", f"{prefix}:bonus_split")),
        (DIVIDEND, lambda: Classification("dividend", "declared", f"{prefix}:dividend")),
        (CLARIFICATION, lambda: Classification("press_release", "clarification", f"{prefix}:clarification")),
    ]
    hits = [make() for rx, make in signals if rx.search(text)]
    if not hits:
        return default
    primary, others = hits[0], hits[1:]
    also = sorted({h.category for h in others if h.category not in (primary.category, "unclassified")})
    details = {**primary.details, **({"also": also} if also else {})}
    return Classification(primary.category, primary.subtype, primary.rule, details)


def classify(subject: str | None, text: str | None) -> Classification:
    s = (subject or "").strip()
    t = (text or "").strip()
    both = f"{s} {t}"
    sl = s.lower()

    def c(category: str, subtype: str | None, rule: str, **details) -> Classification:
        return Classification(category, subtype, rule, details)

    # 1. routine by construction
    if "declaration of nav" in sl:
        return c("unclassified", "nav", "subject:nav")
    if "trading window" in sl:
        return c("unclassified", "trading_window", "subject:trading_window")
    if ESOP.search(both) and not RESULTS.search(t):
        return c("unclassified", "esop", "esop")
    if ROUTINE_SUBJECT.search(s):
        return c("unclassified", "compliance", "subject:compliance")
    if "newspaper" in sl:
        if RESULTS.search(t):
            return c("results", "newspaper_ad", "subject:newspaper+results")
        return c("unclassified", "newspaper", "subject:newspaper")

    # 2. the exchange's own subject line
    if INSIDER.search(both):
        return c("insider_trading", "disclosure", "insider")
    if PLEDGE.search(both):
        return c("pledging", "pledge", "pledge")
    if "credit rating" in sl or (not s and RATING.search(t)):
        return c("credit_rating", _rating_action(t), "subject:credit_rating")
    if re.search(r"insolvency|actions? initiated|orders? passed|litigation|dispute|default", s, re.I):
        return c("litigation", "insolvency" if re.search(r"insolvency|cirp", both, re.I) else "action",
                 "subject:litigation")
    if re.search(r"acquisition|amalgamation|merger|demerger|arrangement|joint venture|divest|disposal", s, re.I):
        return c("m_and_a", "subsidiary" if SUBSIDIARY.search(t) else "transaction", "subject:m_and_a")
    if re.search(r"bagging|receiving of orders|orders/contracts|award of (order|contract)", s, re.I):
        return c("press_release", "order_win", "subject:order_win")
    if re.search(r"change in director|change in management|\bkmp\b|appointment|resignation|cessation"
                 r"|retirement|re-?designation", s, re.I):
        return _mgmt(t or s, "subject:management")
    if "dividend" in sl:
        return c("dividend", "declared", "subject:dividend")
    if "record date" in sl:
        if DIVIDEND.search(t):
            return c("dividend", "record_date", "subject:record_date+dividend")
        if BONUS_SPLIT.search(t):
            return c("bonus_split", "record_date", "subject:record_date+bonus_split")
        return c("unclassified", "compliance", "subject:record_date")
    if re.search(r"\bbonus\b|split|sub-?division", s, re.I):
        return c("bonus_split", "corporate_action", "subject:bonus_split")
    if BUYBACK.search(both):
        return c("fund_raise", "buyback", "buyback")
    if re.search(r"fund ?rais|alteration of capital|allotment of securities|issue of securities|\bqip\b"
                 r"|preferential|rights issue|commercial paper|debenture|\bncd", s, re.I):
        if FUND.search(t):
            return c("fund_raise", "raise", "subject:fund_raise")
        return c("unclassified", "allotment", "subject:allotment")
    if POSTAL.search(both):
        return c("postal_ballot", "ballot", "postal_ballot")
    if re.search(r"shareholders? meeting|general meeting|\bagm\b|\begm\b", s, re.I):
        return c("agm_egm", "meeting", "subject:agm_egm")
    if re.search(r"board meeting intimation|prior intimation|intimation of board meeting", s, re.I):
        # an upcoming meeting: what it will consider decides its weight
        for rx, category in ((RESULTS, "results"), (BUYBACK, "fund_raise"), (FUND, "fund_raise"),
                             (BONUS_SPLIT, "bonus_split"), (DIVIDEND, "dividend")):
            if rx.search(t):
                return c(category, "intimation", f"subject:board_meeting+{category}")
        return c("unclassified", "board_meeting", "subject:board_meeting")
    if "outcome of board meeting" in sl:
        return _from_text(t, "filing", c("unclassified", "board_outcome", "subject:board_outcome"),
                          "board_outcome")
    if re.search(r"financial result|integrated filing.{0,3}financial|\bresults\b", s, re.I):
        return c("results", "filing", "subject:results")
    if "investor presentation" in sl:
        return c("results", "presentation", "subject:investor_presentation")
    if re.search(r"analyst|investor meet|con\.? ?call|earnings call", s, re.I):
        if re.search(r"transcript", t, re.I):
            return c("earnings_call", "transcript", "subject:call+transcript")
        if re.search(r"recording|audio|video|webcast", t, re.I):
            return c("earnings_call", "recording", "subject:call+recording")
        if re.search(r"earnings? call|con(ference)?[\s.-]?call|investor call", t, re.I):
            return c("earnings_call", "notice", "subject:call+notice")
        return c("investor_meetings", "meeting", "subject:investor_meeting")
    if re.search(r"capex|capacity|commercial production|expansion", s, re.I):
        return c("capex", "capex", "subject:capex")

    # 3. generic subjects: read the description
    pr_like = re.search(r"press release|updates?|clarification|regulation 30|spurt", s, re.I) or not s
    default = c("press_release", "general", "text:none") if pr_like else c("unclassified", "other", "text:none")
    return _from_text(t, "press_release", default, "text")
