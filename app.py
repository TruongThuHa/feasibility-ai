"""
feasibility-ai — Thẩm định dự án đầu tư với AI hỗ trợ
=====================================================
Giao diện Streamlit + lớp báo cáo Claude API.
Phần tính số nằm trong engine.py (có test: pytest -q).

Nguyên tắc: MỌI CON SỐ do code Python tính. AI chỉ diễn giải và viết khuyến
nghị; guardrail đối chiếu lại mọi con số trong báo cáo AI với dữ liệu nguồn.

Chạy:
    pip install -r requirements.txt
    streamlit run app.py
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from engine import (
    MAX_VARIABLE_COST_RATIO, RISK_DRIVERS, TORNADO_SPREAD, build_cashflow,
    build_payload, cashflow_array, check_report_numbers, offline_report,
    run_monte_carlo, scenario_analysis, summarize, tornado,
)

# =====================================================================
# LỚP AI (Claude API chỉ diễn giải, không tính số)
# =====================================================================

SYSTEM_PROMPT = """Bạn là chuyên viên thẩm định dự án đầu tư.
Nhiệm vụ: viết báo cáo thẩm định (feasibility report) bằng tiếng Việt,
CHỈ dựa trên số liệu JSON được cung cấp.
Quy tắc về số liệu:
- Chỉ dùng đúng các con số có trong JSON, được phép làm tròn.
- Giữ nguyên đơn vị tiền tệ của JSON, không quy đổi đơn vị.
- KHÔNG tự tính thêm số mới (chênh lệch, tỷ lệ mới...) và KHÔNG đưa số
  liệu thị trường bên ngoài. Nếu cần, mô tả bằng lời.
Cấu trúc báo cáo (markdown):
1. Tóm tắt điều hành: kết luận Go/No-Go ngay đầu
2. Đánh giá hiệu quả tài chính (NPV, IRR, thời gian hoàn vốn, PI so với ngưỡng)
3. Phân tích rủi ro (Monte Carlo: P(NPV>0), khoảng P5–P95; tornado: biến nhạy nhất)
4. Phân tích kịch bản (xấu / cơ sở / tốt)
5. Khuyến nghị và điều kiện kèm theo (3–5 điểm hành động cụ thể)
Văn phong: chuyên nghiệp, súc tích."""

DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")


def generate_report(payload_json: str, api_key: str | None = None,
                    model: str = DEFAULT_MODEL) -> str:
    import anthropic  # pip install anthropic
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("Thiếu ANTHROPIC_API_KEY (nhập trong app hoặc đặt biến môi trường).")
    client = anthropic.Anthropic(api_key=key)
    msg = client.messages.create(
        model=model, max_tokens=3000, system=SYSTEM_PROMPT,
        messages=[{"role": "user",
                   "content": f"Số liệu thẩm định dự án:\n```json\n{payload_json}\n```\n"
                              f"Hãy viết báo cáo thẩm định theo cấu trúc đã nêu."}],
    )
    return "".join(b.text for b in msg.content if b.type == "text")


def show_guardrail(report: str, payload_json: str) -> None:
    result = check_report_numbers(report, payload_json)
    if not result["unverified"]:
        st.success(f"🛡️ Guardrail: cả {result['checked']} con số trong báo cáo "
                   f"đều khớp dữ liệu nguồn.")
    else:
        st.warning(f"🛡️ Guardrail: {len(result['unverified'])}/{result['checked']} "
                   f"con số KHÔNG tìm thấy trong dữ liệu nguồn. Cần kiểm tra trước khi dùng:")
        st.table(pd.DataFrame(result["unverified"]).rename(
            columns={"token": "Con số", "context": "Ngữ cảnh"}))


# =====================================================================
# GIAO DIỆN STREAMLIT
# =====================================================================

SAMPLE_CASES = {
    "ECOFFEE (startup bã cà phê tái chế)": {
        "project_name": "ECOFFEE — Bộ vệ sinh cá nhân từ bã cà phê tái chế + PLA",
        "currency_unit": "triệu VND", "years": 5,
        "capex": 2800.0, "working_capital": 400.0, "salvage_value": 300.0,
        "revenue_year1": 2400.0, "revenue_growth": 0.25,
        "variable_cost_ratio": 0.52, "fixed_cost_year1": 780.0,
        "fixed_cost_growth": 0.08, "tax_rate": 0.20, "discount_rate": 0.16,
    },
    "Dự án sản xuất 5 năm (mẫu tổng quát)": {
        "project_name": "Dự án sản xuất 5 năm", "currency_unit": "triệu VND",
        "years": 5, "capex": 1000.0, "working_capital": 100.0,
        "salvage_value": 100.0, "revenue_year1": 800.0, "revenue_growth": 0.15,
        "variable_cost_ratio": 0.45, "fixed_cost_year1": 200.0,
        "fixed_cost_growth": 0.05, "tax_rate": 0.20, "discount_rate": 0.14,
    },
}


@st.cache_data(show_spinner="Đang chạy Monte Carlo...")
def cached_monte_carlo(assumptions: dict, n_sims: int) -> dict:
    return run_monte_carlo(assumptions, n_sims=n_sims)


def main():
    st.set_page_config(page_title="feasibility-ai", page_icon="📊", layout="wide")

    st.sidebar.title("📊 feasibility-ai")
    st.sidebar.caption("Số do code tính · AI diễn giải · Guardrail kiểm chứng")

    picked = st.sidebar.selectbox("Case mẫu", list(SAMPLE_CASES.keys()))
    base = SAMPLE_CASES[picked]

    st.sidebar.subheader("Giả định dự án")
    a = {}
    a["project_name"] = st.sidebar.text_input("Tên dự án", base["project_name"])
    a["currency_unit"] = st.sidebar.text_input("Đơn vị tiền", base["currency_unit"])
    a["years"] = st.sidebar.number_input("Vòng đời (năm)", 2, 20, int(base["years"]))
    a["capex"] = st.sidebar.number_input("CAPEX", 0.0, value=float(base["capex"]), step=100.0)
    a["working_capital"] = st.sidebar.number_input("Vốn lưu động", 0.0, value=float(base["working_capital"]), step=50.0)
    a["salvage_value"] = st.sidebar.number_input("Giá trị thanh lý", 0.0, value=float(base["salvage_value"]), step=50.0)
    a["revenue_year1"] = st.sidebar.number_input("Doanh thu năm 1", 0.0, value=float(base["revenue_year1"]), step=100.0)
    a["revenue_growth"] = st.sidebar.slider("Tăng trưởng doanh thu/năm", 0.0, 1.0, float(base["revenue_growth"]), 0.01)
    a["variable_cost_ratio"] = st.sidebar.slider("Chi phí biến đổi (% doanh thu)", 0.0, 0.85, float(base["variable_cost_ratio"]), 0.01)
    a["fixed_cost_year1"] = st.sidebar.number_input("Chi phí cố định năm 1", 0.0, value=float(base["fixed_cost_year1"]), step=50.0)
    a["fixed_cost_growth"] = st.sidebar.slider("Tăng chi phí cố định/năm", 0.0, 0.5, float(base["fixed_cost_growth"]), 0.01)
    a["tax_rate"] = st.sidebar.slider("Thuế TNDN", 0.0, 0.5, float(base["tax_rate"]), 0.01)
    a["discount_rate"] = st.sidebar.slider("Suất chiết khấu (WACC)", 0.01, 0.5, float(base["discount_rate"]), 0.01)
    n_sims = st.sidebar.select_slider("Số lần mô phỏng", [1000, 2000, 5000, 10000], 5000)

    # ----- tính toán -----
    df = build_cashflow(a)
    cf = cashflow_array(a)
    metrics = summarize(a["discount_rate"], cf)
    mc = cached_monte_carlo(a, n_sims)
    tor_rows, base_npv = tornado(a)
    scenarios = scenario_analysis(a)
    unit = a["currency_unit"]

    st.title(a["project_name"])
    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["💰 Dòng tiền & chỉ số", "🎲 Monte Carlo", "🌪️ Độ nhạy", "🧭 Kịch bản", "🤖 Báo cáo AI"])

    with tab1:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("NPV", f"{metrics['npv']:,.0f} {unit}",
                  delta="Khả thi" if metrics["npv"] > 0 else "Chưa khả thi")
        c2.metric("IRR", f"{metrics['irr']:.1%}" if metrics["irr"] is not None else "n/a",
                  delta=f"WACC {a['discount_rate']:.0%}")
        pp = metrics["payback_years"]
        c3.metric("Hoàn vốn", f"{pp:.1f} năm" if pp is not None else "—")
        dpp = metrics["discounted_payback_years"]
        c4.metric("Hoàn vốn có chiết khấu", f"{dpp:.1f} năm" if dpp is not None else "—")
        pi = metrics["profitability_index"]
        c5.metric("PI", f"{pi:.2f}" if pi is not None else "—")

        fig = go.Figure()
        fig.add_bar(x=df["year"], y=df["net_cash_flow"], name="Dòng tiền thuần",
                    marker_color=np.where(df["net_cash_flow"] >= 0, "#2a9d8f", "#e76f51"))
        fig.add_scatter(x=df["year"], y=df["cumulative_ncf"], name="Lũy kế",
                        mode="lines+markers", line=dict(color="#264653", width=3))
        fig.add_hline(y=0, line_dash="dot", line_color="gray")
        fig.update_layout(title="Dòng tiền thuần theo năm", xaxis_title="Năm",
                          yaxis_title=unit, height=420)
        st.plotly_chart(fig, width="stretch")
        st.dataframe(df.round(1), width="stretch", hide_index=True)

    with tab2:
        s = mc["stats"]
        c1, c2, c3 = st.columns(3)
        c1.metric("P(NPV > 0)", f"{s['prob_npv_positive']:.0%}")
        c2.metric("NPV trung bình", f"{s['npv_mean']:,.0f} {unit}")
        c3.metric("Khoảng P5–P95", f"[{s['npv_p5']:,.0f}; {s['npv_p95']:,.0f}]")
        fig = px.histogram(x=mc["npvs"], nbins=60, labels={"x": f"NPV ({unit})"},
                           title=f"Phân phối NPV — {s['n_sims']:,} lần mô phỏng")
        fig.add_vline(x=0, line_color="#e76f51", line_width=2, annotation_text="NPV = 0")
        fig.add_vline(x=s["npv_mean"], line_dash="dash", line_color="#264653",
                      annotation_text="Trung bình")
        fig.update_layout(height=440, showlegend=False)
        st.plotly_chart(fig, width="stretch")
        spreads = ", ".join(f"{lbl} ±{sp:.0%}" for _k, lbl, sp in RISK_DRIVERS)
        st.caption(f"Phân phối tam giác, các biến lấy mẫu độc lập: {spreads}. "
                   f"Tỷ lệ chi phí biến đổi bị chặn ở {MAX_VARIABLE_COST_RATIO:.0%}.")

    with tab3:
        labels = [r["label"] for r in tor_rows][::-1]
        lows = [r["npv_low"] - base_npv for r in tor_rows][::-1]
        highs = [r["npv_high"] - base_npv for r in tor_rows][::-1]
        fig = go.Figure()
        fig.add_bar(y=labels, x=lows, base=base_npv, orientation="h",
                    name=f"Biến giảm {TORNADO_SPREAD:.0%}", marker_color="#e9c46a")
        fig.add_bar(y=labels, x=highs, base=base_npv, orientation="h",
                    name=f"Biến tăng {TORNADO_SPREAD:.0%}", marker_color="#264653")
        fig.add_vline(x=base_npv, line_dash="dot", line_color="#e76f51",
                      annotation_text=f"NPV cơ sở {base_npv:,.0f}")
        fig.update_layout(barmode="overlay",
                          title=f"Tornado — tác động ±{TORNADO_SPREAD:.0%} từng biến lên NPV",
                          xaxis_title=f"NPV ({unit})", height=420)
        st.plotly_chart(fig, width="stretch")
        st.caption("Biến trên cùng ảnh hưởng mạnh nhất → ưu tiên quản trị rủi ro biến đó.")

    with tab4:
        rows = []
        name_vi = {"worst": "Xấu (Worst)", "base": "Cơ sở (Base)", "best": "Tốt (Best)"}
        for name, m in scenarios.items():
            rows.append({
                "Kịch bản": name_vi[name],
                f"NPV ({unit})": round(m["npv"], 0),
                "IRR": f"{m['irr']:.1%}" if m["irr"] is not None else "—",
                "Hoàn vốn (năm)": f"{m['payback_years']:.1f}" if m["payback_years"] is not None else "—",
                "PI": f"{m['profitability_index']:.2f}" if m["profitability_index"] is not None else "—",
            })
        sdf = pd.DataFrame(rows)
        st.dataframe(sdf, width="stretch", hide_index=True)
        fig = px.bar(sdf, x="Kịch bản", y=f"NPV ({unit})", color="Kịch bản",
                     title="NPV theo kịch bản",
                     color_discrete_sequence=["#e76f51", "#e9c46a", "#2a9d8f"])
        fig.add_hline(y=0, line_dash="dot")
        fig.update_layout(height=400, showlegend=False)
        st.plotly_chart(fig, width="stretch")

    with tab5:
        st.markdown("**Nguyên tắc:** mọi con số do code Python tính. Claude chỉ *diễn giải* "
                    "và viết khuyến nghị. Sau khi có báo cáo, **guardrail** tự đối chiếu "
                    "từng con số với dữ liệu nguồn.")
        api_key = st.text_input("ANTHROPIC_API_KEY (bỏ trống nếu đã đặt biến môi trường)",
                                type="password")
        payload = build_payload(a, metrics, mc["stats"], tor_rows, scenarios)
        col_a, col_b = st.columns(2)
        if col_a.button("🤖 Sinh báo cáo đầy đủ (Claude API)", type="primary"):
            with st.expander("JSON gửi cho AI (minh bạch đầu vào)"):
                st.code(payload, language="json")
            try:
                with st.spinner("Claude đang viết báo cáo..."):
                    report = generate_report(payload, api_key=api_key or None)
                show_guardrail(report, payload)
                st.markdown(report)
                st.download_button("Tải báo cáo (.md)", report,
                                   file_name="feasibility_report.md")
            except Exception as e:
                st.error(str(e))
        if col_b.button("⚡ Bản rút gọn (không cần API)"):
            report = offline_report(a, metrics, mc["stats"])
            show_guardrail(report, payload)
            st.markdown(report)


if __name__ == "__main__":
    main()
