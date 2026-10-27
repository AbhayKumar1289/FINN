import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AlertRule, Company, PortfolioCompany

SEED_FILE = Path(__file__).parent / "seed_data" / "portfolio.json"

# Category names follow the companion reference document. "category:subtype" narrows a
# rule, e.g. order wins are press releases, but only order wins should alert.
DEFAULT_ALERT_CATEGORIES = ["results", "management_change", "m_and_a", "fund_raise", "litigation",
                            "credit_rating", "pledging", "press_release:order_win"]

DEFAULT_RULES = [
    {"rule_type": "price_move", "threshold": 5.0, "config": {"unit": "abs_pct"}},
    {"rule_type": "volume_spike", "threshold": 2.0, "config": {"lookback": 20}},
    {"rule_type": "announcement_category", "threshold": None,
     "config": {"categories": DEFAULT_ALERT_CATEGORIES, "min_score": 40}},
]


def seed(db: Session) -> None:
    for row in json.loads(SEED_FILE.read_text(encoding="utf-8")):
        company = db.scalar(select(Company).where(Company.nse_symbol == row["nse"]))
        if company is None:
            company = Company(nse_symbol=row["nse"], bse_code=row.get("bse"), name=row["name"],
                              sector=row.get("sector"), is_financial=row.get("financial", False),
                              meta={})
            db.add(company)
            db.flush()
        if row.get("legal_name") and (company.meta or {}).get("legal_name") != row["legal_name"]:
            company.meta = {**(company.meta or {}), "legal_name": row["legal_name"]}
        if db.scalar(select(PortfolioCompany).where(PortfolioCompany.company_id == company.id)) is None:
            db.add(PortfolioCompany(company_id=company.id))
    for r in DEFAULT_RULES:
        if db.scalar(select(AlertRule).where(AlertRule.rule_type == r["rule_type"])) is None:
            db.add(AlertRule(**r))
    db.commit()
