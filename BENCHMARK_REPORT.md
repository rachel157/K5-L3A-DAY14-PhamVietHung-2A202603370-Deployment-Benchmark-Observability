# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây được lấy trực tiếp từ report JSON/CSV và kết quả chạy thực tế.

**Họ tên:** Phạm Việt Hùng
**Ngày chạy:** 2026-11-25
**Môi trường:** Windows 11 + Ubuntu 24.04 (WSL2), Python 3.12.3

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
| :--- | :--- | :--- |
| p95 latency `/ask` | `< 500 ms` | Với mock latency nền ~120ms + jitter ~60ms + retrieval ~20ms, 95% request bình thường hoàn thành dưới 300ms; ngưỡng 500ms đủ để phát hiện nghẽn concurrency hoặc tail latency tăng bất thường mà không báo động giả. |
| Error rate `/ask` | `< 2.0 %` | `MOCK_ERROR_RATE` mặc định là `0.01` (1%); cho phép sai số nhẹ nhưng vẫn bắt được khi upstream lỗi tăng cao. |
| Accuracy trên golden dataset | `≥ 85 %` | Đảm bảo chất lượng RAG (`v2`) vượt trội so với baseline `v1` và chặn deploy nếu có regression. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
| :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| 1 | 4.00 | 192.8 | 224.3 | 1709.9 | 1.67% | PASS |
| 10 | 33.65 | 190.6 | 226.0 | 1708.1 | 1.67% | PASS |
| 50 | 103.27 | 209.7 | 301.2 | 1705.6 | 1.00% | PASS |
| 100 | 50.22 | 648.7 | 3807.2 | 4175.9 | 0.67% | FAIL (`p95 > 500ms`) |

**Nhận xét:** RPS không tăng tuyến tính mãi theo concurrency. Từ concurrency `1 → 10 → 50`, RPS tăng mạnh (`4.00 → 33.65 → 103.27 req/s`) nhờ I/O async xử lý song song các khoảng chờ `await asyncio.sleep(...)`, nhưng tới concurrency `100` thì RPS tụt xuống `50.22 req/s` và `p50/p95/p99` vọt lên `648.7 / 3807.2 / 4175.9 ms` do single-process event loop / connection pool bị bão hoà hàng đợi.

### 2.2 Tail latency (`--requests 300 --concurrency 20`)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
| :--- | ---: | ---: | ---: |
| 0 | 192.6 | 219.6 | 228.5 |
| 0.03 (mặc định) | 243.4 | 236.2 | 1707.0 |
| 0.1 | 374.4 | 1698.1 | 1725.0 |

**Nhận xét:** `p99` và `p95` nhạy hơn rất nhiều so với `avg`: khi `MOCK_SLOW_RATE=0.03`, `avg` chỉ tăng `~50.8 ms` (`192.6 → 243.4 ms`) nhưng `p99` nhảy từ `228.5 ms` lên `1707.0 ms`; khi lên `0.1` (> 5% request chậm), cả `p95` cũng nhảy vọt lên `1698.1 ms` trong khi `avg` mới là `374.4 ms`. Vì vậy đặt SLO theo `average` sẽ che giấu nhóm người dùng đang phải chờ gần 2 giây; SLO phải đặt theo `p95`/`p99`.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
| :--- | ---: | ---: | ---: |
| Accuracy | 4.3% (`1/23`) | 91.3% (`21/23`) | 100.0% (`23/23`) |
| Avg tokens / câu | 55.5 | 108.7 | 113.7 |
| Tổng cost (USD) | $0.000382 | $0.000756 | $0.000790 |
| Cost / câu đúng (USD) | $0.00038175 | $0.00003599 | $0.00003436 |
| Quality gate | FAIL | PASS | PASS |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
| :--- | :--- | :--- |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry `(["hpa", "kubernetes", "autoscal"], ...)` mô tả Kubernetes HPA scale theo CPU, memory và custom metrics vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` (và đồng bộ sang `production/utils/mock_llm.py`). |
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry `(["jwt"], ...)` mô tả JWT là token có chữ ký số và thời điểm hết hạn vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` (và `production/utils/mock_llm.py`). |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**
`v2` tốn khoảng gấp đôi token mỗi câu (`108.7`–`113.7` so với `55.5`) và tăng nhẹ `p95` (`~218–219 ms` so với `188.7 ms`) do thêm bước retrieval và đưa context vào prompt, nhưng độ chính xác tăng từ `4.3%` lên `100.0%`, kéo **cost / câu trả lời đúng** giảm hơn **11 lần** (`$0.00038175` xuống `$0.00003436`). Ngoài ra, đã thêm workflow CI [`.github/workflows/eval.yml`](.github/workflows/eval.yml) chạy `run_eval.py --min-accuracy 0.85` (exit code `1` nếu dưới ngưỡng hoặc có regression) để chặn merge PR kém chất lượng.

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [ ] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals)
- [ ] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian)
- [ ] Một trace lỗi trong Jaeger (có event `exception`)
- [ ] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing**

### 4.1b Trả lời Exercise 7.4

> *[Chờ chạy Docker stack `CP8` để điền số liệu & quan sát thực tế]*

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
| :--- | :--- | :--- | :--- | :--- |
| A | `MOCK_ERROR_RATE=0.2` | | | |
| B | `MOCK_SLOW_RATE=0.3` | | | |
| C | `LLM_MODEL=mock-llm-large` | | | |
| D | `docker pause` 1 instance | | | |
| E | `AGENT_VERSION=v1` | | | |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

> *[Chờ hoàn tất `CP8`]*

### 4.3 Debug bằng trace

> *[Chờ chạy Docker stack `CP8` để lấy `trace_id` và dòng log JSON thực tế]*

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | | | | | |
| 3 | | | | | |

**Giải thích kết quả:**

> *[Chờ chạy Locust headless `CP8`]*

---

## 6. Kết luận

> *[Chờ hoàn tất `CP8`]*
