"""
feasibility-ai — engine tài chính và guardrail
==============================================
Toàn bộ phần TÍNH SỐ nằm ở đây: hàm thuần (pure functions), không phụ thuộc
Streamlit, nên test được bằng pytest (xem test_engine.py).

Nguyên tắc của dự án: mọi con số do code tính. AI chỉ diễn giải, và
`check_report_numbers()` đối chiếu lại mọi con số AI viết ra với dữ liệu nguồn.
"""
from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd

# =====================================================================
# 1. CHỈ SỐ THẨM ĐỊNH
# =====================================================================


def npv(rate: float, cashflows) -> float:
    """NPV, với cashflows[0] là năm 0 (thường là -CAPEX - vốn lưu động)."""
    cf = np.asarray(cashflows, dtype=float)
    t = np.arange(len(cf))
    return float(np.sum(cf / (1 + rate) ** t))


def irr(cashflows, lo: float = -0.99, hi: float = 10.0):
    """IRR bằng phương pháp chia đôi (bisection).

    Trả về None nếu NPV không đổi dấu trên [lo, hi]. Lưu ý: dòng tiền đổi
    dấu nhiều lần có thể có nhiều IRR; hàm này chỉ trả về một nghiệm.
    """
    cf = np.asarray(cashflows, dtype=float)
    f_lo, f_hi = npv(lo, cf), npv(hi, cf)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid, cf)
        if abs(f_mid) < 1e-9:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def payback_period(cashflows):
    """Thời gian hoàn vốn (năm), nội suy tuyến tính trong năm hoàn vốn."""
    cum = np.cumsum(np.asarray(cashflows, dtype=float))
    for i in range(1, len(cum)):
        if cum[i] >= 0:
            prev, flow = cum[i - 1], cum[i] - cum[i - 1]
            return (i - 1) + (-prev / flow if flow != 0 else 0.0)
    return None


def discounted_payback_period(rate: float, cashflows):
    cf = np.asarray(cashflows, dtype=float)
    disc = cf / (1 + rate) ** np.arange(len(cf))
    return payback_period(disc)


def profitability_index(rate: float, cashflows):
    """PI = PV(dòng tiền năm 1..N) / |đầu tư ban đầu|."""
    cf = np.asarray(cashflows, dtype=float)
    invest = -cf[0]
    if invest <= 0:
        return None
    t = np.arange(1, len(cf))
    return float(np.sum(cf[1:] / (1 + rate) ** t) / invest)


def summarize(rate: float, cashflows) -> dict:
    return {
        "npv": npv(rate, cashflows),
        "irr": irr(cashflows),
        "payback_years": payback_period(cashflows),
        "discounted_payback_years": discounted_payback_period(rate, cashflows),
        "profitability_index": profitability_index(rate, cashflows),
        "discount_rate": rate,
    }


# =====================================================================
# 2. DÒNG TIỀN
# =====================================================================


def build_cashflow(a: dict) -> pd.DataFrame:
    """Giả định -> bảng dòng tiền theo năm (0..N).

    Mô hình tiền khả thi: DT -> CP biến đổi -> CP cố định -> EBITDA
    -> khấu hao đường thẳng -> EBIT -> thuế (= 0 khi lỗ, KHÔNG chuyển lỗ)
    -> LNST -> + khấu hao = NCF. Năm 0: -CAPEX - VLĐ.
    Năm cuối: + thu hồi VLĐ + giá trị thanh lý (chưa tính thuế thanh lý).
    """
    n = int(a["years"])
    years = np.arange(0, n + 1)

    revenue = np.zeros(n + 1)
    revenue[1:] = a["revenue_year1"] * (1 + a["revenue_growth"]) ** np.arange(n)
    var_cost = revenue * a["variable_cost_ratio"]
    fixed = np.zeros(n + 1)
    fixed[1:] = a["fixed_cost_year1"] * (1 + a["fixed_cost_growth"]) ** np.arange(n)
    ebitda = revenue - var_cost - fixed
    dep = np.zeros(n + 1)
    dep[1:] = (a["capex"] - a["salvage_value"]) / n
    ebit = ebitda - dep
    tax = np.where(ebit > 0, ebit * a["tax_rate"], 0.0)
    ncf = (ebit - tax) + dep
    ncf[0] = -(a["capex"] + a["working_capital"])
    ncf[-1] += a["working_capital"] + a["salvage_value"]

    df = pd.DataFrame({
        "year": years, "revenue": revenue, "variable_cost": var_cost,
        "fixed_cost": fixed, "ebitda": ebitda, "depreciation": dep,
        "ebit": ebit, "tax": tax, "net_income": ebit - tax,
        "net_cash_flow": ncf,
    })
    df["cumulative_ncf"] = df["net_cash_flow"].cumsum()
    return df


def cashflow_array(a: dict) -> np.ndarray:
    return build_cashflow(a)["net_cash_flow"].to_numpy()


# =====================================================================
# 3. RỦI RO: MONTE CARLO, TORNADO, KỊCH BẢN
# =====================================================================

# (biến, nhãn, biên độ dao động quanh giá trị cơ sở)
RISK_DRIVERS = [
    ("revenue_year1", "Doanh thu năm 1", 0.20),
    ("revenue_growth", "Tăng trưởng doanh thu", 0.30),
    ("variable_cost_ratio", "Tỷ lệ chi phí biến đổi", 0.15),
    ("fixed_cost_year1", "Chi phí cố định năm 1", 0.15),
    ("capex", "Vốn đầu tư (CAPEX)", 0.10),
]
TORNADO_SPREAD = 0.20
MAX_VARIABLE_COST_RATIO = 0.99  # chặn trên: CP biến đổi không vượt doanh thu


def run_monte_carlo(assumptions: dict, n_sims: int = 5000, seed: int = 42) -> dict:
    """Lấy mẫu phân phối tam giác (min, mode, max) quanh giá trị cơ sở.

    Giới hạn: các biến được lấy mẫu ĐỘC LẬP (không mô hình tương quan).
    """
    rng = np.random.default_rng(seed)
    rate = assumptions["discount_rate"]
    npvs = np.empty(n_sims)
    irrs = np.full(n_sims, np.nan)

    for i in range(n_sims):
        a = dict(assumptions)
        for key, _lbl, spread in RISK_DRIVERS:
            base = assumptions[key]
            a[key] = rng.triangular(base * (1 - spread), base, base * (1 + spread))
        a["variable_cost_ratio"] = min(a["variable_cost_ratio"], MAX_VARIABLE_COST_RATIO)
        cf = cashflow_array(a)
        npvs[i] = npv(rate, cf)
        r = irr(cf)
        if r is not None:
            irrs[i] = r

    valid = irrs[~np.isnan(irrs)]
    return {
        "npvs": npvs,
        "stats": {
            "n_sims": n_sims,
            "npv_mean": float(np.mean(npvs)),
            "npv_median": float(np.median(npvs)),
            "npv_p5": float(np.percentile(npvs, 5)),
            "npv_p95": float(np.percentile(npvs, 95)),
            "prob_npv_positive": float(np.mean(npvs > 0)),
            "irr_mean": float(np.mean(valid)) if valid.size else None,
        },
    }


def tornado(assumptions: dict, spread: float = TORNADO_SPREAD):
    """Độ nhạy one-at-a-time ±spread. Trả về (rows xếp theo tác động, NPV cơ sở)."""
    rate = assumptions["discount_rate"]
    base_npv = npv(rate, cashflow_array(assumptions))
    rows = []
    for key, label, _ in RISK_DRIVERS:
        lo_a, hi_a = dict(assumptions), dict(assumptions)
        lo_a[key] = assumptions[key] * (1 - spread)
        hi_a[key] = min(assumptions[key] * (1 + spread), MAX_VARIABLE_COST_RATIO) \
            if key == "variable_cost_ratio" else assumptions[key] * (1 + spread)
        n_lo = npv(rate, cashflow_array(lo_a))
        n_hi = npv(rate, cashflow_array(hi_a))
        rows.append({"driver": key, "label": label, "npv_low": n_lo,
                     "npv_high": n_hi, "impact": abs(n_hi - n_lo)})
    rows.sort(key=lambda r: r["impact"], reverse=True)
    return rows, base_npv


SCENARIOS = {
    "worst": {"revenue_year1": -0.20, "revenue_growth": -0.30,
              "variable_cost_ratio": +0.15, "fixed_cost_year1": +0.15, "capex": +0.10},
    "base": {},
    "best": {"revenue_year1": +0.20, "revenue_growth": +0.30,
             "variable_cost_ratio": -0.15, "fixed_cost_year1": -0.15, "capex": -0.10},
}


def scenario_analysis(assumptions: dict) -> dict:
    out = {}
    for name, shifts in SCENARIOS.items():
        a = dict(assumptions)
        for key, pct in shifts.items():
            a[key] = assumptions[key] * (1 + pct)
        a["variable_cost_ratio"] = min(a["variable_cost_ratio"], MAX_VARIABLE_COST_RATIO)
        out[name] = summarize(a["discount_rate"], cashflow_array(a))
    return out


# =====================================================================
# 4. PAYLOAD GỬI CHO AI
# =====================================================================


def build_payload(assumptions, base_metrics, mc_stats, tornado_rows, scenarios) -> str:
    """JSON duy nhất AI được nhìn thấy. Mọi con số AI dùng phải nằm ở đây."""
    return json.dumps({
        "assumptions": assumptions,
        "base_case_metrics": base_metrics,
        "monte_carlo": mc_stats,
        "monte_carlo_spreads": {k: s for k, _l, s in RISK_DRIVERS},
        "tornado_spread": TORNADO_SPREAD,
        "tornado_top_drivers": tornado_rows[:5],
        "scenarios": scenarios,
        "scenario_shifts": SCENARIOS,
    }, ensure_ascii=False, indent=2, default=str)


def offline_report(a: dict, m: dict, s: dict) -> str:
    """Báo cáo rút gọn không cần API (demo khi không có key)."""
    unit = a.get("currency_unit", "")
    verdict = "GO" if (m["npv"] > 0 and s["prob_npv_positive"] >= 0.7) else (
        "CẦN THẬN TRỌNG" if m["npv"] > 0 else "NO-GO")
    irr_txt = f"{m['irr']:.1%}" if m["irr"] is not None else "n/a"
    pp = m["payback_years"]
    pp_txt = f"{pp:.1f} năm" if pp is not None else "không hoàn vốn trong vòng đời dự án"
    return (f"## Kết luận sơ bộ: **{verdict}**\n\n"
            f"- NPV = {m['npv']:,.0f} {unit} (chiết khấu {m['discount_rate']:.0%})\n"
            f"- IRR = {irr_txt} | Hoàn vốn: {pp_txt}\n"
            f"- Monte Carlo ({s['n_sims']:,} lần): P(NPV>0) = {s['prob_npv_positive']:.0%}, "
            f"P5–P95 = [{s['npv_p5']:,.0f}; {s['npv_p95']:,.0f}] {unit}\n\n"
            f"*Bản đầy đủ: nhập API key và bấm nút Sinh báo cáo.*")


# =====================================================================
# 5. GUARDRAIL: ĐỐI CHIẾU CON SỐ TRONG BÁO CÁO AI VỚI DỮ LIỆU NGUỒN
# =====================================================================
# Ý tưởng: rút mọi con số trong báo cáo, thử các cách đọc (kiểu Việt
# "2.800,5" và kiểu Anh "2,800.5"), rồi so với tập số "được phép" lấy từ
# payload JSON (kèm dạng x100 cho tỷ lệ %). Sai số cho phép = nửa đơn vị
# của chữ số cuối cùng được viết ra (vì AI được phép làm tròn).
# Số nào không khớp -> đưa vào danh sách CẦN KIỂM TRA (không tự kết luận
# là bịa, vì có thể là số tự suy ra hợp lệ; người đọc quyết định).

_NUM_RE = re.compile(r"(?<![\w.,])([-−–]?)(\d[\d.,]*\d|\d)(\s?%)?")
_THOUSANDS_DOT = re.compile(r"^\d{1,3}(\.\d{3})+$")
_THOUSANDS_COMMA = re.compile(r"^\d{1,3}(,\d{3})+$")


def _flatten_numbers(obj) -> list[float]:
    out = []
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        return [float(obj)]
    if isinstance(obj, dict):
        for v in obj.values():
            out += _flatten_numbers(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out += _flatten_numbers(v)
    return out


def _decimals(s: str) -> int:
    return len(s.split(".")[1]) if "." in s else 0


def _interpretations(body: str) -> list[tuple[float, int]]:
    """Các cách đọc có thể của một chuỗi số -> [(giá trị, số chữ số thập phân)]."""
    cands = []
    if "." in body and "," in body:
        if body.rfind(",") > body.rfind("."):          # 2.800,5 (kiểu Việt)
            norm = body.replace(".", "").replace(",", ".")
        else:                                          # 2,800.5 (kiểu Anh)
            norm = body.replace(",", "")
        cands.append(norm)
    elif "," in body:
        if _THOUSANDS_COMMA.match(body):
            cands.append(body.replace(",", ""))        # 2,800
        cands.append(body.replace(",", "."))           # 13,2
    elif "." in body:
        if _THOUSANDS_DOT.match(body):
            cands.append(body.replace(".", ""))        # 2.800
        cands.append(body)                             # 13.2
    else:
        cands.append(body)
    result = []
    for c in cands:
        try:
            result.append((float(c), _decimals(c)))
        except ValueError:
            pass
    return result


def extract_numbers(text: str) -> list[dict]:
    """Rút các con số đáng kiểm tra trong văn bản (bỏ số thứ tự nhỏ, năm lịch)."""
    found = []
    for m in _NUM_RE.finditer(text):
        sign, body, pct = m.group(1), m.group(2), m.group(3)
        plain_int = body.isdigit()
        if plain_int and not pct and (int(body) <= 10 or 1900 <= int(body) <= 2100):
            continue  # số mục, số năm vòng đời, năm lịch -> bỏ qua
        start, end = max(0, m.start() - 30), min(len(text), m.end() + 30)
        found.append({
            "token": m.group(0).strip(),
            "negative": bool(sign),
            "percent": bool(pct),
            "values": _interpretations(body),
            "context": text[start:end].replace("\n", " ").strip(),
        })
    return found


def check_report_numbers(report: str, payload_json: str) -> dict:
    """Đối chiếu mọi con số trong báo cáo AI với payload.

    Trả về {"checked": số lượng con số đã kiểm, "unverified": [các số không khớp]}.
    """
    source = _flatten_numbers(json.loads(payload_json))
    allowed = []
    for v in source:
        allowed += [abs(v), abs(v) * 100]   # x100: tỷ lệ 0.132 viết thành 13,2%

    items = extract_numbers(report)
    unverified = []
    for it in items:
        ok = False
        for value, dec in it["values"]:
            tol = 0.5 * 10 ** (-dec) + 1e-9
            if any(abs(value - a) <= tol for a in allowed):
                ok = True
                break
        if not ok:
            unverified.append({"token": it["token"], "context": it["context"]})
    return {"checked": len(items), "unverified": unverified}
