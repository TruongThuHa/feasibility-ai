"""
feasibility-ai — Thẩm định dự án đầu tư với AI hỗ trợ
=======================================================================
1 FILE DUY NHAT: engine tai chinh + Monte Carlo + tornado + Streamlit UI
+ lop bao cao Claude API.

Nguyen tac: MOI CON SO do code Python tinh (deterministic, co the test).
AI/LLM CHI dien giai ket qua va viet khuyen nghi — khong bao gio tu bia so.

Chay:
    pip install -r requirements.txt
    streamlit run app.py
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# =====================================================================
# PHAN 1 — ENGINE TAI CHINH (pure functions, khong side effect)
# =====================================================================

def npv(rate: float, cashflows) -> float:
    """NPV voi cashflows[0] la nam 0 (thuong la -CAPEX)."""
    cf = np.asarray(cashflows, dtype=float)
    t = np.arange(len(cf))
    return float(np.sum(cf / (1 + rate) ** t))


def irr(cashflows, lo: float = -0.99, hi: float = 10.0):
    """IRR bang bisection. Tra ve None neu NPV khong doi dau tren [lo, hi]."""
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
    """Thoi gian hoan von, noi suy tuyen tinh trong nam."""
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
    """PI = PV(dong tien nam 1..N) / |dau tu ban dau|."""
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


# ------------------------- Dung dong tien ---------------------------

def build_cashflow(a: dict) -> pd.DataFrame:
    """Gia dinh -> DataFrame dong tien theo nam (0..N).

    Mo hinh pre-feasibility: DT -> chi phi bien doi -> chi phi co dinh
    -> EBITDA -> khau hao duong thang -> EBIT -> thue (clamp 0 khi lo)
    -> LNST -> +khau hao = NCF. Nam 0: -CAPEX - VLD.
    Nam cuoi: +thu hoi VLD +thanh ly.
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


# --------------------- Monte Carlo & do nhay ------------------------

RISK_DRIVERS = [
    ("revenue_year1", "Doanh thu nam 1", 0.20),
    ("revenue_growth", "Tang truong doanh thu", 0.30),
    ("variable_cost_ratio", "Ty le chi phi bien doi", 0.15),
    ("fixed_cost_year1", "Chi phi co dinh nam 1", 0.15),
    ("capex", "Von dau tu (CAPEX)", 0.10),
]


def run_monte_carlo(assumptions: dict, n_sims: int = 5000, seed: int = 42) -> dict:
    """Lay mau phan phoi tam giac (min, mode, max) quanh gia tri co so."""
    rng = np.random.default_rng(seed)
    rate = assumptions["discount_rate"]
    npvs = np.empty(n_sims)
    irrs = np.full(n_sims, np.nan)

    for i in range(n_sims):
        a = dict(assumptions)
        for key, _lbl, spread in RISK_DRIVERS:
            base = assumptions[key]
            a[key] = rng.triangular(base * (1 - spread), base, base * (1 + spread))
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


def tornado(assumptions: dict, spread: float = 0.20):
    """One-at-a-time +/-spread. Tra ve (rows sorted theo tac dong, NPV co so)."""
    rate = assumptions["discount_rate"]
    base_npv = npv(rate, cashflow_array(assumptions))
    rows = []
    for key, label, _ in RISK_DRIVERS:
        lo_a, hi_a = dict(assumptions), dict(assumptions)
        lo_a[key] = assumptions[key] * (1 - spread)
        hi_a[key] = assumptions[key] * (1 + spread)
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
        out[name] = summarize(a["discount_rate"], cashflow_array(a))
    return out


# =====================================================================
# PHAN 2 — LOP AI (Claude API chi dien giai, khong tinh so)
# =====================================================================

SYSTEM_PROMPT = """Ban la chuyen vien tham dinh du an dau tu cao cap.
Nhiem vu: viet bao cao tham dinh (feasibility report) bang tieng Viet,
CHI dua tren so lieu JSON duoc cung cap. TUYET DOI khong tu bia them so lieu.
Cau truc bao cao (markdown):
1. Tom tat dieu hanh — ket luan Go/No-Go ngay dau
2. Danh gia hieu qua tai chinh (dien giai NPV, IRR, PP, DPP, PI so voi nguong)
3. Phan tich rui ro (Monte Carlo: P(NPV>0), khoang P5-P95; tornado: driver nhay nhat)
4. Phan tich kich ban (worst/base/best)
5. Khuyen nghi va dieu kien kem theo (3-5 diem hanh dong cu the)
Van phong: chuyen nghiep, sung tich, so lieu dan chung trong ngoac."""


def build_payload(assumptions, base_metrics, mc_stats, tornado_rows, scenarios) -> str:
    return json.dumps({
        "assumptions": assumptions,
        "base_case_metrics": base_metrics,
        "monte_carlo": mc_stats,
        "tornado_top_drivers": tornado_rows[:5],
        "scenarios": scenarios,
    }, ensure_ascii=False, indent=2, default=str)


def generate_report(payload_json: str, api_key: str | None = None,
                    model: str = "claude-sonnet-4-5") -> str:
    import anthropic  # pip install anthropic
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("Thieu ANTHROPIC_API_KEY (nhap trong app hoac dat bien moi truong).")
    client = anthropic.Anthropic(api_key=key)
    msg = client.messages.create(
        model=model, max_tokens=3000, system=SYSTEM_PROMPT,
        messages=[{"role": "user",
                   "content": f"So lieu tham dinh du an:\n```json\n{payload_json}\n```\n"
                              f"Hay viet bao cao tham dinh theo cau truc da neu."}],
    )
    return "".join(b.text for b in msg.content if b.type == "text")


def offline_report(a: dict, m: dict, s: dict) -> str:
    """Bao cao rut gon khong can API — demo khi khong co key."""
    unit = a.get("currency_unit", "")
    verdict = "GO" if (m["npv"] > 0 and s["prob_npv_positive"] >= 0.7) else (
        "CAN THAN TRONG" if m["npv"] > 0 else "NO-GO")
    irr_txt = f"{m['irr']:.1%}" if m["irr"] is not None else "n/a"
    pp = m["payback_years"]
    pp_txt = f"{pp:.1f} nam" if pp is not None else "khong hoan von trong vong doi"
    return (f"## Ket luan so bo: **{verdict}**\n\n"
            f"- NPV = {m['npv']:,.0f} {unit} (chiet khau {m['discount_rate']:.0%})\n"
            f"- IRR = {irr_txt} | Hoan von: {pp_txt}\n"
            f"- Monte Carlo ({s['n_sims']:,} lan): P(NPV>0) = {s['prob_npv_positive']:.0%}, "
            f"P5–P95 = [{s['npv_p5']:,.0f}; {s['npv_p95']:,.0f}] {unit}\n\n"
            f"*Ban day du: nhap API key va bam nut Sinh bao cao.*")


# =====================================================================
# PHAN 3 — GIAO DIEN STREAMLIT
# =====================================================================

SAMPLE_CASES = {
    "ECOFFEE (startup ba ca phe tai che)": {
        "project_name": "ECOFFEE — Bo ve sinh ca nhan tu ba ca phe tai che + PLA",
        "currency_unit": "trieu VND", "years": 5,
        "capex": 2800.0, "working_capital": 400.0, "salvage_value": 300.0,
        "revenue_year1": 2400.0, "revenue_growth": 0.25,
        "variable_cost_ratio": 0.52, "fixed_cost_year1": 780.0,
        "fixed_cost_growth": 0.08, "tax_rate": 0.20, "discount_rate": 0.16,
    },
    "Du an san xuat 5 nam (mau tong quat)": {
        "project_name": "Du an san xuat 5 nam", "currency_unit": "trieu VND",
        "years": 5, "capex": 1000.0, "working_capital": 100.0,
        "salvage_value": 100.0, "revenue_year1": 800.0, "revenue_growth": 0.15,
        "variable_cost_ratio": 0.45, "fixed_cost_year1": 200.0,
        "fixed_cost_growth": 0.05, "tax_rate": 0.20, "discount_rate": 0.14,
    },
}


def main():
    st.set_page_config(page_title="feasibility-ai", page_icon="📊", layout="wide")

    st.sidebar.title("📊 feasibility-ai")
    st.sidebar.caption("So do code tinh · AI dien giai")

    picked = st.sidebar.selectbox("Case mau", list(SAMPLE_CASES.keys()))
    base = SAMPLE_CASES[picked]

    st.sidebar.subheader("Gia dinh du an")
    a = {}
    a["project_name"] = st.sidebar.text_input("Ten du an", base["project_name"])
    a["currency_unit"] = st.sidebar.text_input("Don vi tien", base["currency_unit"])
    a["years"] = st.sidebar.number_input("Vong doi (nam)", 2, 20, int(base["years"]))
    a["capex"] = st.sidebar.number_input("CAPEX", 0.0, value=float(base["capex"]), step=100.0)
    a["working_capital"] = st.sidebar.number_input("Von luu dong", 0.0, value=float(base["working_capital"]), step=50.0)
    a["salvage_value"] = st.sidebar.number_input("Gia tri thanh ly", 0.0, value=float(base["salvage_value"]), step=50.0)
    a["revenue_year1"] = st.sidebar.number_input("Doanh thu nam 1", 0.0, value=float(base["revenue_year1"]), step=100.0)
    a["revenue_growth"] = st.sidebar.slider("Tang truong DT/nam", 0.0, 1.0, float(base["revenue_growth"]), 0.01)
    a["variable_cost_ratio"] = st.sidebar.slider("Chi phi bien doi (%DT)", 0.0, 0.95, float(base["variable_cost_ratio"]), 0.01)
    a["fixed_cost_year1"] = st.sidebar.number_input("Chi phi co dinh nam 1", 0.0, value=float(base["fixed_cost_year1"]), step=50.0)
    a["fixed_cost_growth"] = st.sidebar.slider("Tang CP co dinh/nam", 0.0, 0.5, float(base["fixed_cost_growth"]), 0.01)
    a["tax_rate"] = st.sidebar.slider("Thue TNDN", 0.0, 0.5, float(base["tax_rate"]), 0.01)
    a["discount_rate"] = st.sidebar.slider("Suat chiet khau (WACC)", 0.01, 0.5, float(base["discount_rate"]), 0.01)
    n_sims = st.sidebar.select_slider("So lan mo phong", [1000, 2000, 5000, 10000], 5000)

    # ----- tinh toan -----
    df = build_cashflow(a)
    cf = cashflow_array(a)
    metrics = summarize(a["discount_rate"], cf)
    mc = run_monte_carlo(a, n_sims=n_sims)
    tor_rows, base_npv = tornado(a)
    scenarios = scenario_analysis(a)
    unit = a["currency_unit"]

    st.title(a["project_name"])
    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["💰 Dong tien & chi so", "🎲 Monte Carlo", "🌪️ Do nhay", "🧭 Kich ban", "🤖 Bao cao AI"])

    with tab1:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("NPV", f"{metrics['npv']:,.0f} {unit}",
                  delta="Kha thi" if metrics["npv"] > 0 else "Chua kha thi")
        c2.metric("IRR", f"{metrics['irr']:.1%}" if metrics["irr"] is not None else "n/a",
                  delta=f"WACC {a['discount_rate']:.0%}")
        pp = metrics["payback_years"]
        c3.metric("Hoan von", f"{pp:.1f} nam" if pp is not None else "—")
        dpp = metrics["discounted_payback_years"]
        c4.metric("Hoan von CK", f"{dpp:.1f} nam" if dpp is not None else "—")
        pi = metrics["profitability_index"]
        c5.metric("PI", f"{pi:.2f}" if pi is not None else "—")

        fig = go.Figure()
        fig.add_bar(x=df["year"], y=df["net_cash_flow"], name="NCF",
                    marker_color=np.where(df["net_cash_flow"] >= 0, "#2a9d8f", "#e76f51"))
        fig.add_scatter(x=df["year"], y=df["cumulative_ncf"], name="NCF luy ke",
                        mode="lines+markers", line=dict(color="#264653", width=3))
        fig.add_hline(y=0, line_dash="dot", line_color="gray")
        fig.update_layout(title="Dong tien thuan theo nam", xaxis_title="Nam",
                          yaxis_title=unit, height=420)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df.round(1), use_container_width=True, hide_index=True)

    with tab2:
        s = mc["stats"]
        c1, c2, c3 = st.columns(3)
        c1.metric("P(NPV > 0)", f"{s['prob_npv_positive']:.0%}")
        c2.metric("NPV trung binh", f"{s['npv_mean']:,.0f} {unit}")
        c3.metric("Khoang P5–P95", f"[{s['npv_p5']:,.0f}; {s['npv_p95']:,.0f}]")
        fig = px.histogram(x=mc["npvs"], nbins=60, labels={"x": f"NPV ({unit})"},
                           title=f"Phan phoi NPV — {s['n_sims']:,} lan mo phong")
        fig.add_vline(x=0, line_color="#e76f51", line_width=2, annotation_text="NPV = 0")
        fig.add_vline(x=s["npv_mean"], line_dash="dash", line_color="#264653",
                      annotation_text="Trung binh")
        fig.update_layout(height=440, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Bien rui ro theo phan phoi tam giac: DT nam 1 ±20%, "
                   "tang truong ±30%, CP bien doi ±15%, CP co dinh ±15%, CAPEX ±10%.")

    with tab3:
        labels = [r["label"] for r in tor_rows][::-1]
        lows = [r["npv_low"] - base_npv for r in tor_rows][::-1]
        highs = [r["npv_high"] - base_npv for r in tor_rows][::-1]
        fig = go.Figure()
        fig.add_bar(y=labels, x=lows, base=base_npv, orientation="h",
                    name="-20%", marker_color="#e76f51")
        fig.add_bar(y=labels, x=highs, base=base_npv, orientation="h",
                    name="+20%", marker_color="#2a9d8f")
        fig.add_vline(x=base_npv, line_dash="dot", line_color="#264653",
                      annotation_text=f"NPV co so {base_npv:,.0f}")
        fig.update_layout(barmode="overlay",
                          title="Tornado — tac dong ±20% tung bien len NPV",
                          xaxis_title=f"NPV ({unit})", height=420)
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Bien tren cung anh huong manh nhat → uu tien quan tri rui ro bien do.")

    with tab4:
        rows = []
        name_vi = {"worst": "Xau (Worst)", "base": "Co so (Base)", "best": "Tot (Best)"}
        for name, m in scenarios.items():
            rows.append({
                "Kich ban": name_vi[name],
                f"NPV ({unit})": round(m["npv"], 0),
                "IRR": f"{m['irr']:.1%}" if m["irr"] is not None else "—",
                "Hoan von (nam)": round(m["payback_years"], 1) if m["payback_years"] else "—",
                "PI": round(m["profitability_index"], 2) if m["profitability_index"] else "—",
            })
        sdf = pd.DataFrame(rows)
        st.dataframe(sdf, use_container_width=True, hide_index=True)
        fig = px.bar(sdf, x="Kich ban", y=f"NPV ({unit})", color="Kich ban",
                     title="NPV theo kich ban",
                     color_discrete_sequence=["#e76f51", "#e9c46a", "#2a9d8f"])
        fig.add_hline(y=0, line_dash="dot")
        fig.update_layout(height=400, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    with tab5:
        st.markdown("**Nguyen tac:** moi con so do code Python tinh. "
                    "Claude chi *dien giai* va viet khuyen nghi — khong tu bia so.")
        api_key = st.text_input("ANTHROPIC_API_KEY (bo trong neu da dat bien moi truong)",
                                type="password")
        col_a, col_b = st.columns(2)
        if col_a.button("🤖 Sinh bao cao day du (Claude API)", type="primary"):
            payload = build_payload(a, metrics, mc["stats"], tor_rows, scenarios)
            with st.expander("JSON gui cho AI (minh bach dau vao)"):
                st.code(payload, language="json")
            try:
                with st.spinner("Claude dang viet bao cao..."):
                    report = generate_report(payload, api_key=api_key or None)
                st.markdown(report)
                st.download_button("Tai bao cao (.md)", report,
                                   file_name="feasibility_report.md")
            except Exception as e:
                st.error(str(e))
        if col_b.button("⚡ Ban rut gon (khong can API)"):
            st.markdown(offline_report(a, metrics, mc["stats"]))


if __name__ == "__main__":
    main()
