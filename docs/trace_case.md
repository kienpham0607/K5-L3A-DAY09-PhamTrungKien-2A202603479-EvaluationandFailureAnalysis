# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Case đã điền — FM-03 ticket_trust trên C-002@11

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11` (chạy lại bằng `lab9.trace_case`; run_id theo seed cố định) |
| Triệu chứng | lab8 grader **FAIL** `status resolved != denied`. Reply: "đã hoàn 20.000đ"; ledger `refund_vnd=20000` trong khi nhãn `denied` / `refund_vnd=0`. |
| Bước sai đầu tiên | **#3 `model_override`** — `{"delay_days": 5}` (tin số ngày trong ticket, không tin DB). |
| Vì sao là bước *đầu tiên* | #1 `handoff` và #2 `investigator` vẫn đọc đúng order từ DB; chỉ từ #3 delay bị ghi đè → #4 `quote` entitlement 20.000đ → refund sai. |
| Failure mode | **FM-03** (`ticket_trust`) trong `docs/failure_taxonomy.md` |
| Đối chứng | `fixed C-002@11`: không có `model_override`; #3 là `quote` `amount_vnd=0` / `no_entitlement`; lab8 **PASS**. |
| Regression test | `tests/test_lab9_trace_case.py::test_fm03_ticket_trust_first_wrong_step` — assert có `model_override` và lab8 fail trên `seeded_regression`, pass trên `fixed`. |
| Chưa chắc chắn | Trace không tách riêng lỗi parse ticket vs lỗi chính sách chọn tin nguồn nào; chỉ chứng minh nguồn delay đã bị override trước khi quote. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
