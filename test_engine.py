"""Test cho engine.py. Chạy: pytest -q

Giá trị kỳ vọng được tính tay hoặc đối chiếu độc lập, không lấy từ chính code.
"""
import json

import pytest

from engine import (
    build_payload, cashflow_array, check_report_numbers, irr, npv,
    offline_report, payback_period, profitability_index, run_monte_carlo,
    scenario_analysis, summarize, tornado,
)

ECOFFEE = {
    "project_name": "ECOFFEE", "currency_unit": "triệu VND", "years": 5,
    "capex": 2800.0, "working_capital": 400.0, "salvage_value": 300.0,
    "revenue_year1": 2400.0, "revenue_growth": 0.25,
    "variable_cost_ratio": 0.52, "fixed_cost_year1": 780.0,
    "fixed_cost_growth": 0.08, "tax_rate": 0.20, "discount_rate": 0.16,
}


# ---------- chỉ số cơ bản (tính tay) ----------

def test_npv_by_hand():
    # -100 + 60/1.1 + 60/1.21 = 4.1322...
    assert npv(0.10, [-100, 60, 60]) == pytest.approx(4.1322, abs=1e-4)


def test_irr_simple_case():
    # -100 + 110/(1+r) = 0  =>  r = 10%
    assert irr([-100, 110]) == pytest.approx(0.10, abs=1e-6)


def test_irr_makes_npv_zero():
    cf = [-1000, 300, 400, 500]
    assert npv(irr(cf), cf) == pytest.approx(0, abs=1e-6)


def test_irr_none_when_no_sign_change():
    assert irr([100, 50, 50]) is None


def test_payback_interpolation():
    # lũy kế: -100, -40, +20  => hoàn vốn = 1 + 40/60 = 1.667 năm
    assert payback_period([-100, 60, 60]) == pytest.approx(1 + 40 / 60)


def test_payback_none_if_never_recovered():
    assert payback_period([-100, 10, 10]) is None


def test_profitability_index():
    # PV(năm 1..2) = 104.1322 / 100
    assert profitability_index(0.10, [-100, 60, 60]) == pytest.approx(1.041322, abs=1e-6)


# ---------- case ECOFFEE (số trên CV) ----------

def test_ecoffee_cashflow_and_npv():
    cf = cashflow_array(ECOFFEE)
    assert cf[0] == pytest.approx(-3200.0)
    assert npv(0.16, cf) == pytest.approx(-266.2, abs=0.1)


def test_ecoffee_monte_carlo_probability():
    s = run_monte_carlo(ECOFFEE, n_sims=5000, seed=42)["stats"]
    assert s["prob_npv_positive"] == pytest.approx(0.326, abs=0.005)


def test_tornado_top_driver_is_variable_cost():
    rows, _ = tornado(ECOFFEE)
    assert rows[0]["driver"] == "variable_cost_ratio"


def test_scenarios_are_ordered():
    sc = scenario_analysis(ECOFFEE)
    assert sc["worst"]["npv"] < sc["base"]["npv"] < sc["best"]["npv"]


def test_variable_cost_ratio_is_capped():
    a = dict(ECOFFEE, variable_cost_ratio=0.95)   # +15% sẽ vượt 100% nếu không chặn
    sc = scenario_analysis(a)
    assert sc["worst"]["npv"] < sc["base"]["npv"]


# ---------- guardrail ----------

@pytest.fixture
def ecoffee_payload():
    m = summarize(0.16, cashflow_array(ECOFFEE))
    s = run_monte_carlo(ECOFFEE, n_sims=2000)["stats"]
    rows, _ = tornado(ECOFFEE)
    return ECOFFEE, m, s, build_payload(ECOFFEE, m, s, rows, scenario_analysis(ECOFFEE))


def test_guardrail_passes_offline_report(ecoffee_payload):
    a, m, s, payload = ecoffee_payload
    result = check_report_numbers(offline_report(a, m, s), payload)
    assert result["checked"] > 0
    assert result["unverified"] == []


def test_guardrail_accepts_vietnamese_format_and_rounding(ecoffee_payload):
    *_, payload = ecoffee_payload
    irr_pct = json.loads(payload)["base_case_metrics"]["irr"] * 100
    report = (f"NPV đạt −266,2 triệu VND, IRR {irr_pct:.1f}%".replace(".", ",")
              + " so với WACC 16%. Vốn đầu tư 2.800 triệu.")
    assert check_report_numbers(report, payload)["unverified"] == []


def test_guardrail_flags_fabricated_number(ecoffee_payload):
    *_, payload = ecoffee_payload
    report = "NPV đạt −266 triệu VND. Thị trường mỹ phẩm xanh tăng 37,5%/năm."
    flagged = [u["token"] for u in check_report_numbers(report, payload)["unverified"]]
    assert flagged == ["37,5%"]


def test_guardrail_ignores_section_numbers_and_years(ecoffee_payload):
    *_, payload = ecoffee_payload
    report = "1. Tóm tắt\n2. Hiệu quả tài chính trong 5 năm, giai đoạn 2026–2030"
    assert check_report_numbers(report, payload)["unverified"] == []
