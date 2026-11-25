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

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals): [`screenshots/grafana-dashboard.png`](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian): [`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (có event `exception`): [`screenshots/jaeger-error-trace.png`](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing**: [`screenshots/prometheus-alert-firing.png`](screenshots/prometheus-alert-firing.png)

### 4.1b Trả lời Exercise 7.4

1. **p95 và avg đang là bao nhiêu? Khoảng cách giữa chúng nói lên điều gì?**
   - Trong lúc tải bình thường (`MOCK_SLOW_RATE=0.03`), `avg ≈ 250–300 ms` và `p95 ≈ 300–700 ms`; khi bật Chaos (`MOCK_SLOW_RATE=0.3`), PromQL đo được `avg ≈ 322 ms` trong khi `p95 ≈ 1.70 s` (trên Grafana ~`1.89–1.90 s`). Khoảng cách lớn giữa `avg` và `p95` cho thấy phân phối latency lệch phải (tail latency cao): đa số request nhanh nhưng có nhóm request chậm bất thường kéo trải nghiệm của 5% user cuối lên gần 2 giây.
2. **Panel "Requests/s theo instance": Nginx có chia đều traffic cho 2 instance không?**
   - Có, Nginx dùng round-robin (`upstream agent_cluster`) nên traffic chia tương đối đều giữa các instance đang chạy (vd trong Grafana `172.21.0.6:8000` và `172.21.0.9:8000` cùng đạt ~`55–60 req/s` ở đỉnh tải, và ~`6–8 req/s` mỗi instance ở tải ổn định).
3. **Vì sao input tokens/s lớn hơn output tokens/s?**
   - Vì ở `agent v2`, mỗi request có thêm `SYSTEM_PROMPT` và đoạn context truy xuất từ `KNOWLEDGE_BASE` ghép vào prompt đầu vào, nên số `input_tokens` luôn lớn hơn `output_tokens` (PromQL đo được `input ≈ 2,009.5 tok/s` so với `output ≈ 1,049.4 tok/s`, gấp ~1.9 lần).
4. **`curl http://localhost:8080/metrics` trả về gì? Vì sao?**
   - Trả về **`404 Not Found`** từ Nginx (`nginx/1.28.3`). Trong `nginx/nginx.conf`, `/metrics` bị chặn ở reverse proxy công khai để tránh lộ thông tin nội bộ (số request, chi phí LLM, instance IP) ra Internet; chỉ Prometheus trong mạng nội bộ `obs_net` mới scrape trực tiếp `agent:8000/metrics`.

### 4.2 Thí nghiệm "phá hệ thống"

*(Đã kiểm chứng `promtool test rules /p/alert_rules_test.yml` → `SUCCESS` trước khi chạy thí nghiệm)*

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
| :--- | :--- | :--- | :--- | :--- |
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | **85s** (`for: 1m` + scrape/eval) | Error rate (`/ask`) & LLM calls theo kết quả (`error`) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (đạt trạng thái `PENDING` ở ngưỡng `>1s` khi test `for: 2m`) | ~120s (`for: 2m`) | Latency `/ask` (`p95`/`p99`) & LLM latency p95 |
| C | Chạy tải cao (`-u 100` / burn rate > `$2/h`) | `LLMCostBurnRateHigh` | **5s** (từ lúc bắt đầu Chaos sau tải cao) | Cost burn rate (`USD/giờ`) & Tokens/s |
| D | Không thực hiện thêm (đã đủ 2 alert firing cùng lúc ở A & C) | — | — | — |
| E | `AGENT_VERSION=v1` | Không alert nào firing | — | Không có metric SLO nào báo đỏ dù chất lượng giảm |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Cần kết hợp **quality evaluation liên tục** (chạy `eval/run_eval.py` trên golden dataset như CI quality gate trước khi deploy) và **online quality monitoring** (theo dõi tỉ lệ `retrieval_hit_ratio` — panel này tụt về 0% ở v1, feedback người dùng thumbs-up/down, hoặc LLM-as-judge chấm mẫu trên traffic production).

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất tìm được trong Jaeger ([`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png)):

- `trace_id`: `ef3a962383acd9563a9d82cc5f87ea19`
- Tổng thời gian: `1702.8 ms` (~`1.7s` trên Jaeger UI)
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (`1676.3 ms`, chiếm **~98.4%** tổng thời gian; so với `agent.retrieve_context` chỉ mất `23.4 ms`)
- Dòng log tương ứng (grep từ `docker compose -p k5-day14-observability logs agent` theo `trace_id`):

```json
{"ts": "2026-11-25T14:00:29.020949+00:00", "level": "INFO", "service": "observable-agent", "instance": "90ccca2060c0", "event": "llm_call", "trace_id": "ef3a962383acd9563a9d82cc5f87ea19", "span_id": "eb00365f2bf34cda", "request_id": "2796210244fe", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 76, "output_tokens": 39, "cost_usd": 3.5e-05, "llm_ms": 1676.3}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

*(Số liệu lấy từ `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv`, dòng `POST /ask` và `Aggregated`)*

| Số instance | RPS (`Aggregated` / `/ask`) | p50 (ms) | p95 (ms) | p99 (ms) | Failures (`/ask`) |
| :--- | ---: | ---: | ---: | ---: | ---: |
| 1 | 64.55 / 58.67 | 200 | 580 | 1700 | 69 / 7,035 (0.98%) |
| 3 | 65.42 / 59.68 | 200 | 260 | 1700 | 66 / 7,155 (0.92%) |

**Giải thích kết quả:** Scale từ 1 lên 3 instance giúp **p95 của `/ask` giảm hơn một nửa (từ `580 ms` xuống `260 ms`)** vì mỗi container chỉ được cấp `0.5 CPU`; khi chỉ có 1 instance xử lý 100 concurrent users thì request bị xếp hàng chờ CPU/event-loop. Còn tổng **RPS gần như giữ nguyên (~65 req/s)** vì nút thắt lúc này nằm ở `wait_time = between(0.5, 2)` phía Locust (tổng tải của 100 user giả lập chỉ tạo tối đa ~60–65 req/s), còn `p99 = 1700 ms` không đổi vì do `MOCK_SLOW_RATE=0.03` nội tại của mock LLM.

---

## 6. Kết luận

- 3 điều học được về benchmark & observability:
  1. Không bao giờ đặt SLO theo latency trung bình (`avg`) vì tail latency (`p95`/`p99`) mới phản ánh trải nghiệm thực tế của người dùng bị chậm.
  2. Ba trụ cột Metrics → Traces → Logs liên kết trực tiếp qua `trace_id` giúp khoanh vùng ngay nguyên nhân chậm/lỗi từ dashboard xuống đúng span và dòng log chi tiết.
  3. Hệ thống khỏe về hạ tầng (CPU, HTTP 200, không alert) vẫn có thể tụt chất lượng nghiêm trọng nếu thiếu **eval trên golden dataset** và **quality gate trong CI**.
- Metric / alert sẽ bổ sung khi lên production thật:
  - Alert cho `retrieval_hit_ratio` tụt xuống dưới ngưỡng (phát hiện suy giảm RAG giống Thí nghiệm E) và alert cho Redis connection pool / rate-limit `429` spike bất thường.
