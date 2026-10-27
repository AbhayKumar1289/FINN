import pytest

from app.finance.calc import (compare_to_guidance, crosses, daily_price_change,
                              margin, pct_change, relative_volume, to_crore)


def test_positive_and_negative_change():
    assert pct_change(110, 100).value == pytest.approx(10)
    assert pct_change(94, 100).value == pytest.approx(-6)


def test_zero_base_is_undefined():
    c = pct_change(50, 0)
    assert c.value is None and "zero" in c.note


def test_negative_base_never_returns_misleading_pct():
    assert pct_change(-60, -100).value is None
    assert pct_change(-60, -100).note == "loss narrowed"
    assert pct_change(-140, -100).note == "loss widened"
    assert pct_change(20, -100).note == "turned positive from a loss"


def test_turned_to_loss_keeps_value_with_note():
    c = pct_change(-20, 100)
    assert c.value == pytest.approx(-120) and c.note == "turned to a loss"


def test_daily_change_needs_two_sessions():
    assert daily_price_change([100]).value is None
    assert daily_price_change([100, 105]).value == pytest.approx(5)


def test_relative_volume_excludes_today():
    vols = [100] * 20 + [250]
    assert relative_volume(vols, 20) == pytest.approx(2.5)


def test_relative_volume_insufficient_history():
    assert relative_volume([100] * 10, 20) is None


def test_threshold_boundary_inclusive():
    assert crosses(2.0, 2.0) is True
    assert crosses(1.999, 2.0) is False
    assert crosses(None, 2.0) is False


def test_units_normalise_to_crore():
    assert to_crore(1, "billion") == 100
    assert to_crore(250, "lakh") == pytest.approx(2.5)
    assert to_crore(10, "million") == pytest.approx(1)
    with pytest.raises(ValueError):
        to_crore(1, "furlongs")


def test_margin_guards():
    assert margin(20, 100) == pytest.approx(20)
    assert margin(20, 0) is None


def test_guidance_comparison():
    assert compare_to_guidance(8, 15)["status"] == "missed"
    assert compare_to_guidance(8, 15)["gap"] == -7
    assert compare_to_guidance(16, 12, 14) == {"status": "exceeded", "gap": 2.0}
    assert compare_to_guidance(13, 12, 14)["status"] == "met"
    assert compare_to_guidance(None, 12)["status"] == "not_comparable"
