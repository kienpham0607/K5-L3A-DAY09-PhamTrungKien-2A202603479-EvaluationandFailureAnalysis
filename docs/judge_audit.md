# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5`

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Có** (κ/P/R đều trên sàn) | **dùng** làm judge phụ cho tone |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không** (κ 0.375 < 0.6; R 0.3 < 0.7) | **loại** — không dùng làm gate |

Ma trận: tone `{tp:24, fp:4, fn:6, tn:66}` · helpful `{tp:9, fp:0, fn:21, tn:70}`.

## ≥5 case audit thủ công
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 (tone) | PASS | FAIL | **Người** | Reply xưng "em…nha" suồng sã. Rubric tone: coi xưng hô không chuẩn CS là FAIL dù có "Dạ". |
| 2 | H-070 (tone) | PASS | FAIL | **Người** | Có emoji 😂 trong ngữ cảnh khiếu nại. Rubric: cấm emoji khi ticket khiếu nại/hoàn tiền. |
| 3 | H-051 (tone) | FAIL | PASS | **Người** | Dùng từ "refund" vẫn đúng CS LogiX. Rubric: không phạt loanword đã được whitelist. |
| 4 | H-081 (tone) | FAIL | PASS | **Judge** | Nhãn người đọc nhầm — câu denied lịch sự là PASS. Hành động: sửa nhãn human → FAIL chỉ khi giọng thô. |
| 5 | HL-015 (helpful) | PASS | FAIL | **Người** | Reply nói hoàn 55.000đ trong khi ledger 40.000đ (`sai tiền`). Judge "helpful" chỉ nhìn lịch sự → **miss 21/30 failure**. |
| 6 | HL-047 (helpful) | PASS | FAIL | **Người** | "Ok bạn…nhé" sai xưng hô + không helpful theo CS. Rubric helpful phải gắn fact (đúng tiền, đúng trạng thái), không chỉ lịch sự. |

## Kết luận
- **Loại `helpful` khỏi gate:** precision = 1.0 nhưng recall chỉ 0.3 (fn=21, fp=0) — judge hầu như chỉ bắt lỗi khi reply thô, còn **bỏ lọt** gần hết case sai tiền / sai xưng hô. κ=0.375 dưới sàn 0.6. Dùng judge này làm gate sẽ để regression FM-08 (reply ≠ ledger) lọt.
- **Giữ `tone_ok` làm tín hiệu phụ** (đạt FLOORS), không thay grader code cho tiền/approval.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai; cần nhãn người mới để có held-out thật.
