# Ghi chú phân tích · Day 04

Họ và tên: Đỗ Minh Hoàng
MSSV: 2A202603554

## 1. Case được chọn

- ID case: **H1** — điều tra GitHub `h02n9572mx9y`, theo liên kết tìm nguyên nhân/ảnh hưởng rồi đối chiếu Cloudflare `yaa0witbl2me`.
- Câu trả lời lần 1 có bảng so sánh hai incident và dẫn liên kết tới bản tổng hợp `xr3myzj7ms51`, nhưng chưa gọi tool đọc bản tổng hợp. Agent còn viết GitHub “kéo dài ~3 ngày”, suy từ mốc tạo/cập nhật thay vì khoảng gián đoạn có bằng chứng.
- Điểm lần 1: **60/100**. Nguồn: phần tử `cases` có `id == "H1"` trong `eval_before.json`.

## 2. Bằng chứng trong trace

Trích rút gọn trace H1 lần 1, chỉ giữ những trường liên quan:

```json
[
  {
    "event": "tool", "step": 1, "name": "get_incident_details",
    "arguments": {"provider": "github", "incident_id": "h02n9572mx9y"},
    "result": {
      "updates": [{
        "status": "resolved",
        "body": "Please refer to the combined summary in this related incident: https://www.githubstatus.com/incidents/xr3myzj7ms51"
      }]
    }
  },
  {
    "event": "tool", "step": 1, "name": "get_incident_details",
    "arguments": {"provider": "cloudflare", "incident_id": "yaa0witbl2me"}
  },
  {"event": "model", "step": 2, "finish": "stop"}
]
```

Không có call đọc `xr3myzj7ms51`. Agent nhìn thấy liên kết nhưng dừng trước khi thu thập nội dung. `grade.mechanical` ghi `tool_calls: 2`, `tool_steps: 1`, áp trần 60 với lý do “Cần tool calls ở ít nhất 2 model steps khác nhau.”

Nguyên nhân có thể xảy ra: prompt ban đầu yêu cầu dùng tool và dẫn nguồn nhưng chưa nêu rõ cần đọc tiếp incident được liên kết. Có URL không đồng nghĩa đã đọc nguồn. Ngoài ra, `updated_at` có thể là lúc cập nhật báo cáo, không phải lúc khôi phục dịch vụ.

## 3. Thay đổi đã thực hiện

- **`SYSTEM_PROMPT` trong `agent.py`:** yêu cầu đọc incident liên quan/bản tổng hợp bằng `get_incident_details` khi cần nguyên nhân/ảnh hưởng; tránh gọi lặp và nêu phần chưa kiểm chứng nếu không đọc được.
- Bổ sung phân biệt `created_at`, `updated_at`, thời gian từng update; không lấy `updated_at` làm thời điểm kết thúc gián đoạn. Yêu cầu nêu giới hạn khi dữ liệu bị cắt/lược bỏ và dẫn nguồn từng provider khi đối chiếu.
- Chọn sửa prompt để giữ vòng lặp đã hoạt động của lần 1, không hard-code ID/câu trả lời. Kiểm tra URL nguồn đã có trước lần eval đầu, nên không tính là cải tiến mới giữa hai file.
- **`providers.py`:** giãn cách yêu cầu mặc định 5 giây, retry tối đa 3 lần với HTTP 429/500/502/503/504, chờ tăng dần 15/30/60 giây và tôn trọng `Retry-After`. Nếu server yêu cầu chờ quá 60 giây thì dừng, không retry sớm. Không retry lỗi 402. Cơ chế dùng chung cho agent và judge trong cùng tiến trình.
- Lý do sửa provider: các lần thử gặp 429/503 tạo case `unscored`. Retry nhằm phục hồi lỗi tạm thời, không sửa dữ liệu hoặc điểm để case pass.
- Kiểm tra offline sau thay đổi: `python -X utf8 -m unittest discover -s tests -v` đạt **42 tests**. Tests retry dùng HTTP giả, không gọi API/chờ thật. Không sửa fixtures, cases, scenarios hoặc grading.

## 4. So sánh hai lần chạy

| Chỉ số | `eval_before.json` | `eval_after.json` |
|---|---|---|
| Case được chấm | 22/22 | 22/22 |
| Điểm tổng | 90,36 | 91,82 |
| Điểm H1 (case được chọn) | 60 | 60 |
| Điểm H2 (quan sát bổ sung) | 50 | 100 |
| Số model calls của agent có usage | 49 | 46 |
| Token agent | 50.775 | 56.044 |
| Token judge | 42.659 | 39.496 |
| Tổng token agent + judge | 93.434 | 95.540 |
| Chi phí agent (USD, trường `usage.cost`) | 0,006816840 | 0,006900979 |
| Chi phí judge (USD, trường `judge_usage.cost`) | 0,004411035 | 0,004284350 |
| Tổng chi phí được ghi nhận (USD) | 0,011227875 | 0,011185329 |

Hai file có cùng `config`: agent/judge provider `openrouter`, cùng model `mistralai/mistral-small-3.2-24b-instruct`, `max_steps = 8`, dataset `core`; dùng snapshot bài chính. Điểm tổng tăng **1,46 điểm**, nhưng token agent tăng dù số model calls giảm.

- **Cải thiện quan sát được:** H2 tăng 50 → 100. Lần 1 chỉ đọc incident `t89g2q1800fr`, thiếu `get_status`. Lần 2 trace có cả `get_incident_details` và `get_status(provider="github", component="Actions")`, nên có bằng chứng riêng về incident lịch sử và trạng thái snapshot. A4 tăng 85 → 90; H7 tăng 88 → 90.
- **Hạ tầng:** hai file cuối cùng đều chấm đủ 22 case, không còn `unscored`. Không suy ra retry khắc phục được mọi loại quota/lỗi API.
- **Chưa giải quyết:** H1 vẫn 60; trace lần 2 vẫn chưa gọi đọc `xr3myzj7ms51`. H6 cũng giữ mức 60, chưa theo liên kết như yêu cầu. H3 giữ mức 50, vẫn không gọi tool để kiểm chứng ID người dùng cung cấp.
- **Case giảm:** E1 từ 100 → 85; A5 từ 95 → 85. Không chỉ báo cáo case tăng điểm. Giải thích của judge cần kiểm tra lại: judge A5 đòi dẫn nguồn cho 23 incident, trong khi tool chỉ trả tối đa 5 incident khớp dù báo có 23 mục khớp trong 50 incident gần nhất.
- **Kết luận:** điểm tổng tăng nhẹ, nhưng prompt chưa đạt mục tiêu chính là làm agent đọc tiếp incident được liên kết. H2 cải thiện là quan sát của lần chạy, chưa đủ để quy toàn bộ mức tăng cho thay đổi prompt.

## 5. Giới hạn

- **Judge:** điểm là đánh giá xấp xỉ; cùng model với agent có thể thiên lệch hoặc giải thích không nhất quán. Cần đối chiếu answer, trace và `grade.mechanical`, không coi điểm cao là bảo đảm mọi claim đúng.
- **Snapshot:** dữ liệu bài chính chụp ngày 09/11/2026, không phản ánh trạng thái live. Chỉ kết luận tại `captured_at`.
- **Phạm vi dữ liệu:** tìm trong 50 incident gần nhất, trả tối đa 5 incident khớp; chi tiết giữ một số updates và cắt mỗi update tối đa 900 ký tự. Không tìm thấy không chứng minh chưa từng có incident; không bảo đảm danh sách đủ cho cả năm 2025.
- **Độ ổn định:** so sánh một kết quả hoàn chỉnh mỗi phiên bản. Trước đó có các lần thử lỗi API/chưa chấm đủ, không dùng điểm tạm thời làm điểm tổng. Chưa đủ dữ liệu để chứng minh cải thiện ổn định hoặc quan hệ nhân quả; không sửa tay điểm/expected.
- **Usage:** model calls tính bằng số phần tử usage của agent, không gồm judge hoặc HTTP retries thất bại. Token/chi phí chỉ cộng các usage lưu trong hai file, không gồm các lần debug/eval lỗi trước đó và không thay thế hóa đơn tài khoản.
- **Retry:** giãn cách chỉ dùng chung trong một tiến trình; hai terminal vẫn có thể cùng chạm quota. Hết credit/quota kéo dài cần xử lý tại provider. Tests offline không chứng minh API thật luôn khả dụng hoặc eval lần sau sẽ tăng điểm.
- Có sử dụng AI hỗ trợ giải thích lỗi, sửa code, chạy tests và tổng hợp báo cáo từ trace. Cần tự đọc và giải thích được code, bằng chứng và các giới hạn khi demo.

## 6. Phần bonus

### Thay đổi triển khai

- `run_agent` lấy `tools.schemas` và `tools.system_prompt` nếu có, fallback về cấu hình bài chính. Bộ bonus dùng năm status tools riêng cho GitHub, Cloudflare, Vercel, npm, DigitalOcean và một tool đọc chi tiết incident.
- Prompt bonus hướng dẫn đọc timeline bằng `next_offset`, dùng offset integer >= 0 và limit integer 1–3. Chỉ đọc tiếp khi câu hỏi cần; không tuyên bố xem toàn bộ timeline nếu còn trang chưa đọc.
- Lỗi tool được gửi lại model với đúng `tool_call_id` để sửa arguments hoặc quyết định retry. Với cùng tên tool và bộ arguments, tối đa ba lần rate limit được thực thi; yêu cầu tiếp theo bị chặn và trace ghi `tool_rejected`. Không giấu lần bị chặn hoặc coi 429 là outage.
- Với rate limit thật, đọc `Retry-After` dạng giây hoặc HTTP date. Chờ tối đa 30 giây trong mỗi khoảng nghỉ của tool; nếu server yêu cầu lâu hơn thì không gọi lại yêu cầu đó trong run, trả kết quả từng phần. Rate limit giả lập có `retry_after_seconds = 0` nên không cần chờ. Retry của status tools tách biệt retry API model trong `providers.py`.
- Dữ liệu `distractors` được giữ nguyên trong trace để kiểm tra, nhưng lược khỏi observation gửi model và thay bằng số lượng mục bị lược. Các incident, updates, nguồn và timestamp vẫn giữ lại. Không sửa fixture hoặc bộ eval.
- Khi đã đọc chi tiết incident của nhiều provider, câu trả lời phải có ít nhất một URL đã quan sát của mỗi provider đó. Đây là kiểm tra sự hiện diện URL, chưa chứng minh toàn bộ claims được nguồn hỗ trợ. Status chỉ có `source` được hướng dẫn dẫn nguồn bằng prompt, chưa bị gate này bắt buộc.
- Tool output vẫn là dữ liệu không đáng tin; prompt cấm làm theo chỉ dẫn giả, bịa trạng thái khi tool lỗi hoặc bịa incident của provider không có công cụ.

### Kiểm tra offline

```powershell
python -X utf8 -m unittest discover -s tests -v
python -X utf8 -m unittest discover -s bonus -p "test_*.py" -v
```

Kết quả triển khai: **42 tests bài chính và 8 tests bonus đều pass**. Tests bổ sung kiểm tra ngừng thực thi sau ba lần rate limit, không bỏ qua Retry-After dài, giữ dữ liệu nhiễu trong trace, truyền đúng cursor/trang timeline và yêu cầu nguồn cho từng provider incident. Tests dùng scripted provider; không đánh giá năng lực LLM thật.

### Kết quả eval bằng model thật

Đã chạy bằng terminal có API key và kiểm tra `eval_bonus.json`: **10/10 case được chấm**, không có case `unscored`. Agent và judge cùng dùng OpenRouter, model `mistralai/mistral-small-3.2-24b-instruct`, dataset `bonus`, `max_steps = 16`.

Lệnh chạy toàn bộ bộ bonus:

```powershell
python -X utf8 evals/run_evals.py --bonus --workers 1 --output eval_bonus.json
```

| Chỉ số | Kết quả |
|---|---:|
| Điểm bộ bonus | 93/100 |
| Điểm bonus quy đổi tham khảo | 13,95/15 |
| B1–B8 | Mỗi case 100 |
| B9 | 80 |
| B10 | 50 |
| Model calls của agent có usage | 26 |
| Token agent | 55.492 |
| Token judge | 30.907 |
| Chi phí agent ghi nhận (USD) | 0,004425218 |
| Chi phí judge ghi nhận (USD) | 0,003338669 |

Bằng chứng hoạt động:

- **B2:** trace đọc Vercel incident `sps6n39gm4sg` ở step 1, rồi đọc tiếp `offset=2, limit=3` ở step 2, tìm được update nói về GitHub-connected builds. Câu trả lời phân biệt incident resolved với trạng thái tại snapshot. Kiểm tra code xác nhận hai tool steps.
- **B3:** hai lần gọi status Vercel, phục hồi sau lỗi 429 giả lập. **B4:** ba lần gọi status Vercel rồi dừng, vẫn cung cấp thông tin GitHub; không bịa trạng thái bên bị rate limit.
- **B5:** phục hồi sau INVALID_ARGUMENTS. **B6:** đối chiếu incident Vercel và npm, không dùng 160 mục nhiễu làm bằng chứng. **B7:** không lặp lại marker injection trong final answer. **B8:** đối chiếu ảnh hưởng DigitalOcean/Vercel với hai nguồn.

Lỗi/giới hạn còn lại:

- **B10:** chỉ gọi `get_vercel_status` một lần và dừng sau 429, dù còn có thể thử lại. Câu trả lời nói “Sẽ thử lại” nhưng trace không có lần gọi tiếp theo; còn thiếu timestamp riêng trong phần trả lời. `grade.mechanical` ghi yêu cầu ít nhất hai lần gọi Vercel và áp trần 50. Guard hiện tại giới hạn số lần retry, chưa bắt buộc model phải thực hiện retry trước khi kết thúc.
- **B9:** agent nói rõ không có tools cho Linear/Slack và không tạo URL incident. Điểm judge là 80 dù lời giải thích đánh giá nội dung phù hợp. Các URL status tham khảo do model đưa ra chưa được tools kiểm chứng; không dùng chúng để xác nhận trạng thái hai dịch vụ.
- Các tình huống rate limit/format/noise/injection trong bộ bonus là giả lập, không chứng minh độ ổn định của public API thật. Chỉ có một run hoàn chỉnh được báo cáo; điểm judge có dao động.
- `13,95/15` là điểm quy đổi tham khảo, cần giảng viên đối chiếu trace, không tự cộng điểm eval bài chính với điểm này để suy ra điểm cuối cùng của lab. Không ghi đè hai kết quả bài chính và không sửa tay điểm bonus.
