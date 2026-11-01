# AI đã được dùng như thế nào trong dự án này

Dự án được xây dựng với trợ lý AI (Claude). Tài liệu này ghi rõ **phần nào AI
làm, phần nào tôi tự kiểm chứng**, vì một công cụ thẩm định chỉ có giá trị
khi con số trong đó đúng.

> ✍️ **Hà tự viết lại các mục có dấu ✍️ bằng lời của mình** trước khi public.
> Chỉ ghi những gì bạn thực sự đã làm.

## 1. Chia việc giữa người và AI

| Việc | AI làm | Tôi làm / kiểm chứng |
|---|---|---|
| Chọn bài toán và case ECOFFEE | Gợi ý các hướng đề tài | Chọn đề tài; giả định ECOFFEE lấy từ kế hoạch kinh doanh của nhóm |
| Kiến trúc "code tính số, AI diễn giải" | Đề xuất, tham khảo FinRobot (AI4Finance) | Hiểu và giải thích được vì sao chọn |
| Code engine (NPV, IRR, Monte Carlo...) | Viết khung code | Đối chiếu công thức với giáo trình Kinh tế Đầu tư |
| Test (`test_engine.py`) | Viết test | Giá trị kỳ vọng tính tay (xem mục 2) |
| Guardrail chống bịa số | Viết hàm `check_report_numbers` | Thử với báo cáo có số bịa để xem nó có bắt được không |
| Báo cáo thẩm định | Claude API viết lời diễn giải | Guardrail + đọc lại kết luận |

## 2. Những gì tôi đã tự kiểm chứng

- **Công thức:** NPV, IRR, thời gian hoàn vốn, PI được kiểm bằng các ví dụ
  tính tay trong `test_engine.py` (ví dụ: dòng tiền −100, 110 → IRR = 10%).
- **Kết quả case ECOFFEE:** NPV = −266,2 triệu VND, IRR = 13,2% < WACC 16%,
  P(NPV > 0) ≈ 33% (5.000 lần mô phỏng, seed 42) → kết luận **NO-GO**.
  Biến nhạy nhất là tỷ lệ chi phí biến đổi.
- ✍️ *Ghi thêm: bạn đã kiểm lại con số nào bằng Excel hoặc tính tay, và
  phát hiện lỗi gì (ví dụ: lỗi chi phí cố định bị nhân theo sản lượng trong
  file Excel ECOFFEE ban đầu).*

## 3. Guardrail hoạt động thế nào

1. Code tính toàn bộ chỉ số → đóng gói thành **một JSON duy nhất** (xem được
   trong app, mục "JSON gửi cho AI").
2. Claude chỉ nhận JSON đó, được dặn không tự tính số mới, không quy đổi đơn vị.
3. Sau khi có báo cáo, `check_report_numbers()` rút **mọi con số** trong báo
   cáo (hiểu cả kiểu viết `2.800,5` và `2,800.5`), so với các số trong JSON,
   cho phép sai số làm tròn.
4. Số nào không khớp được liệt kê kèm ngữ cảnh để người đọc kiểm tra.

Guardrail **không tự kết luận là AI bịa**: một số tự suy ra hợp lệ (ví dụ đổi
triệu sang tỷ) cũng bị đưa vào danh sách. Mục tiêu là không con số nào lọt
qua mà chưa được người kiểm.

## 4. Bài học

✍️ *Viết 3–5 dòng: AI giúp nhanh ở đâu, sai ở đâu, bạn sẽ làm khác gì lần sau.*
