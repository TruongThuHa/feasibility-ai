# feasibility-ai — AI thẩm định dự án đầu tư / phân tích khả thi

> **Code tính số · AI diễn giải.** Công cụ thẩm định dự án đầu tư (investment
> feasibility) với lớp báo cáo AI — dự án cá nhân cho chương trình AI Intern,
> nền tảng Kinh tế Đầu tư.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Streamlit](https://img.shields.io/badge/Streamlit-app-red)
![Claude](https://img.shields.io/badge/Claude-API-orange)

## Bài toán

Thẩm định một dự án đầu tư thực: nhập bộ giả định (CAPEX, vốn lưu động, doanh thu
+ tăng trưởng, chi phí, thuế, WACC) → công cụ tính **toàn bộ chỉ số hiệu quả tài
chính** → **lượng hóa rủi ro** → AI viết **báo cáo thẩm định + khuyến nghị Go/No-Go**.

Case study kèm sẵn: **ECOFFEE** — startup sản xuất bộ vệ sinh cá nhân từ bã cà phê
tái chế + nhựa sinh học PLA, đón đầu lệnh cấm nhựa dùng một lần tại Hà Nội 2026.

## Tính năng

- **Chỉ số thẩm định:** NPV, IRR (bisection tự cài đặt), thời gian hoàn vốn (PP)
  có nội suy, hoàn vốn chiết khấu (DPP), chỉ số sinh lời (PI)
- **Monte Carlo:** 1.000–10.000 kịch bản, phân phối tam giác trên 5 biến rủi ro,
  tính xác suất P(NPV > 0) và khoảng tin cậy P5–P95
- **Tornado chart:** phân tích độ nhạy one-at-a-time ±20%, xếp hạng biến rủi ro
- **Phân tích kịch bản:** worst / base / best
- **Báo cáo AI (Claude API):** sinh báo cáo thẩm định 5 phần chuẩn mực bằng
  tiếng Việt, kèm nút xem nguyên văn JSON gửi cho AI (minh bạch đầu vào)

## Kiến trúc: tách bạch số và chữ

```
┌─────────────────────────┐      ┌──────────────────────────┐
│  LỚP TÍNH TOÁN (Python) │      │  LỚP DIỄN GIẢI (Claude)  │
│  deterministic          │ ───▶ │  chỉ nhận JSON kết quả   │
│  NPV · IRR · PP · PI    │ JSON │  viết báo cáo, khuyến    │
│  Monte Carlo · Tornado  │      │  nghị — KHÔNG tự bịa số  │
└─────────────────────────┘      └──────────────────────────┘
```

LLM không bao giờ tự tính hay tự sinh số liệu. Mọi con số trong báo cáo đều truy
vết được về code — loại bỏ hallucination số liệu ngay từ thiết kế (pattern học
từ kiến trúc FinRobot của AI4Finance).

## Cài đặt & chạy

```bash
pip install -r requirements.txt
streamlit run app.py
```

Tab **🤖 Báo cáo AI** cần API key của Anthropic — nhập trực tiếp trong app hoặc:

```bash
export ANTHROPIC_API_KEY=sk-ant-...     # Linux/macOS
setx ANTHROPIC_API_KEY sk-ant-...       # Windows
```

Không có key vẫn dùng được 4 tab còn lại + nút "Bản rút gọn (không cần API)".

## Cấu trúc repo

```
feasibility-ai/
├── app.py            # TẤT CẢ trong 1 file: engine + Monte Carlo + UI + lớp AI
├── requirements.txt
├── AI_WORKFLOW.md    # tài liệu hóa quy trình dùng AI khi làm project
├── README.md
└── .gitignore
```

## AI được dùng ở đâu?

Xem [`AI_WORKFLOW.md`](AI_WORKFLOW.md) — ghi lại toàn bộ quy trình AI-assisted
development 5 bước (kèm nguyên văn prompt): nghiên cứu kiến trúc → sinh khung
code → **AI review công thức tài chính** → viết test từ giá trị tính tay → viết
tài liệu. Đây là phần trọng tâm cho bài trình bày "sử dụng AI hỗ trợ trong quá
trình làm project".

## Disclaimer

Dự án phục vụ mục đích học tập. Không phải tư vấn đầu tư.
