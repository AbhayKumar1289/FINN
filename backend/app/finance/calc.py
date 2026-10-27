"""Deterministic financial calculations. The LLM never does arithmetic."""
from dataclasses import dataclass
from statistics import mean
from typing import Optional, Sequence

UNIT_TO_CRORE = {
    "crore": 1.0, "cr": 1.0,
    "lakh": 0.01, "lakhs": 0.01,
    "million": 0.1, "mn": 0.1,
    "billion": 100.0, "bn": 100.0,
    "thousand": 1e-4,
    "rupees": 1e-7, "inr": 1e-7,
}


@dataclass(frozen=True)
class Change:
    value: Optional[float]          # percent, None when not meaningful
    note: Optional[str] = None      # human-readable caveat

    def as_dict(self) -> dict:
        return {"value": None if self.value is None else round(self.value, 2), "note": self.note}


def to_crore(value: float, unit: str) -> float:
    key = unit.strip().lower()
    if key not in UNIT_TO_CRORE:
        raise ValueError(f"Unknown unit: {unit!r}")
    return value * UNIT_TO_CRORE[key]


def pct_change(current: Optional[float], base: Optional[float]) -> Change:
    """Growth from base to current, with honest handling of zero/negative bases."""
    if current is None or base is None:
        return Change(None, "missing value")
    if base == 0:
        return Change(None, "base is zero; growth undefined")
    if base < 0:
        if current >= 0:
            return Change(None, "turned positive from a loss")
        return Change(None, "loss narrowed" if current > base else "loss widened")
    value = (current - base) / base * 100
    if current < 0:
        return Change(value, "turned to a loss")
    return Change(value)


def daily_price_change(closes: Sequence[float]) -> Change:
    """Last close vs previous close. Pass split/dividend-ADJUSTED closes."""
    if len(closes) < 2:
        return Change(None, "need at least two sessions")
    return pct_change(closes[-1], closes[-2])


def relative_volume(volumes: Sequence[float], lookback: int = 20) -> Optional[float]:
    """Today's volume / mean of the previous `lookback` sessions (today excluded)."""
    if lookback < 1 or len(volumes) < lookback + 1:
        return None
    prior = volumes[-lookback - 1:-1]
    avg = mean(prior)
    if avg <= 0:
        return None
    return volumes[-1] / avg


def margin(numerator: Optional[float], revenue: Optional[float]) -> Optional[float]:
    if numerator is None or revenue is None or revenue <= 0:
        return None
    return numerator / revenue * 100


def crosses(observed: Optional[float], threshold: float) -> bool:
    """Inclusive boundary: observed == threshold triggers."""
    return observed is not None and observed >= threshold


def compare_to_guidance(actual: Optional[float], low: Optional[float],
                        high: Optional[float] = None) -> dict:
    """Compare an actual figure with a point (low only) or range (low..high) guidance.
    gap is actual minus nearest bound, in the same unit as the guidance."""
    if actual is None or low is None:
        return {"status": "not_comparable", "gap": None}
    hi = high if high is not None else low
    lo, hi = min(low, hi), max(low, hi)
    if actual < lo:
        return {"status": "missed", "gap": round(actual - lo, 2)}
    if actual > hi:
        return {"status": "exceeded", "gap": round(actual - hi, 2)}
    return {"status": "met", "gap": 0.0}
