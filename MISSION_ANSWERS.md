# Day 14 Lab — Mission Answers

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secrets trong mã nguồn (dòng 17–18):** `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"` — nếu push lên GitHub public sẽ lộ thông tin nhạy cảm ngay lập tức.
2. **Hardcode cấu hình (dòng 21–22):** `DEBUG = True`, `MAX_TOKENS = 500` không đọc từ biến môi trường nên không thể đổi cấu hình theo môi trường (dev/staging/prod) mà không sửa code.
3. **Dùng `print()` thay cho structured logging và lộ secret ra log (dòng 33–38):** `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` làm rò rỉ API key vào stdout/log aggregator và khó lọc/truy vấn log.
4. **Thiếu health check endpoint (dòng 42–43):** Không có `GET /health` hay `GET /ready`, nên container orchestrator hoặc cloud platform không biết khi nào process treo hoặc chưa sẵn sàng.
5. **Hardcode `host="localhost"`, `port=8000` và bật `reload=True` (dòng 49–54):** `localhost` không nhận traffic từ bên ngoài container, `port=8000` không dùng `PORT` do Railway/Render inject, còn `reload=True` gây tốn tài nguyên và không ổn định ở production.
6. **Không xử lý graceful shutdown:** Không có `lifespan` hay xử lý `SIGTERM`, dễ cắt ngang request đang chạy khi restart/deploy.

### Exercise 1.2: Kết quả chạy bản `develop`

```text
POST http://localhost:8000/ask?question=Hello
HTTP/1.1 200 OK
content-type: application/json

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

### Exercise 1.3: Bảng so sánh `develop` vs `production`

| Feature | Develop (`develop/app.py`) | Production (`production/app.py` + `config.py`) | Tại sao quan trọng? |
| :--- | :--- | :--- | :--- |
| Config | Hardcode (`DEBUG = True`, `MAX_TOKENS = 500`) | Đọc từ biến môi trường qua `Settings` (`os.getenv(...)`) | Áp dụng 12-Factor: tách biệt code và config, đổi môi trường không cần sửa code |
| Secrets | Hardcode `OPENAI_API_KEY`, `DATABASE_URL` | Đọc `OPENAI_API_KEY`, `AGENT_API_KEY` từ env / `.env` (git-ignored) | Tránh lộ secret trên Git và dễ rotate key |
| Host & Port | Cố định `host="localhost"`, `port=8000`, `reload=True` | `HOST=0.0.0.0`, `PORT` từ env var, tắt reload | Container/PaaS bắt buộc bind `0.0.0.0` và inject động `PORT` |
| Health check | Không có | `GET /health` (liveness: status, uptime, version, env) | Platform phát hiện lỗi để restart và route traffic đúng lúc |
| Logging | `print(...)` (còn in cả API key) | `logging` xuất JSON (`json.dumps(...)`), không log secret | Dễ parse, tìm kiếm, cảnh báo tập trung mà không rò rỉ dữ liệu nhạy cảm |
| Shutdown | Tắt đột ngột | `lifespan` chuyển readiness về `False`, hoàn thành request đang xử lý | Tránh lỗi 502/mất dữ liệu người dùng khi rolling deploy |

---

## Part 2: Docker

### Exercise 2.1: Câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11` (bản Python đầy đủ gồm OS + toolchain, kích thước lớn).
2. **Working directory:** `/app` (`WORKDIR /app` — thư mục làm việc mặc định bên trong container).
3. **Tại sao `COPY requirements.txt` trước `COPY . .` / `COPY app.py`:** Tận dụng Docker layer cache; khi chỉ sửa code ứng dụng mà `requirements.txt` không đổi, Docker dùng lại layer `pip install` đã cache thay vì cài lại từ đầu.
4. **CMD vs ENTRYPOINT:** `CMD` cung cấp lệnh/tham số mặc định và có thể bị ghi đè dễ dàng khi chạy `docker run <image> <cmd>`; `ENTRYPOINT` cố định file thực thi chính của container (các tham số ở `CMD` sẽ được truyền làm đối số cho `ENTRYPOINT`).

### Exercise 2.2 – 2.4: Build, kích thước image & Docker Compose stack

- **Build & chạy container `develop`:**

```http
POST http://localhost:18000/ask?question=What%20is%20Docker
HTTP/1.1 200 OK
content-type: application/json

{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

- **So sánh kích thước image (`docker images`):**
  - `my-agent:develop` (single-stage `python:3.11`): **1.15 GB** (~1,150 MB)
  - `my-agent:advanced` (multi-stage `python:3.11-slim`): **163 MB**
  - **Chênh lệch:** giảm **~85.8%** dung lượng vì stage `runtime` chỉ copy `/root/.local` (các package đã cài) và code chạy, loại bỏ `gcc`, `libpq-dev`, cache build và base OS nặng.
- **Sơ đồ kiến trúc stack `02-docker/production/docker-compose.yml`:**

```text
Client ──▶ Nginx (:80/:443) ──▶ Agent (:8000) ──▶ Redis (:6379)
                                       └────────▶ Qdrant (:6333)
```

- **Kết quả test qua Nginx (`http://localhost/health` & `POST /ask`):**

```http
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json

{"status":"ok","uptime_seconds":13.0,"version":"2.0.0","timestamp":"2026-11-25T13:46:16.896552"}
```

```http
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json

{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

---

## Part 3: Cloud Deployment

### Exercise 3.1 – 3.2: Deploy Agent Part 6 & So sánh `railway.toml` vs `render.yaml`

- **URL public:** https://k5-l3a-day14-phamviethung-2a202603370.onrender.com (Render Docker Web Service + Render Key Value Redis `k5-day14-redis`, region Singapore).
- **Kiểm tra 4 lệnh CP6:** `GET /health` → `200`, `GET /ready` → `200`, `POST /ask` không có key → `401`, `POST /ask` có `X-API-Key` → `200`.
- **Ảnh minh chứng:** [`screenshots/dashboard.png`](screenshots/dashboard.png), [`screenshots/running.png`](screenshots/running.png), [`screenshots/test.png`](screenshots/test.png).
- **So sánh `railway.toml` và `render.yaml`:**
  - `railway.toml` dùng định dạng **TOML**, tập trung cấu hình build/deploy cho **một service** (`[build] builder = "DOCKERFILE"`, `[deploy] healthcheckPath = "/health"`, `restartPolicyType`), còn biến môi trường và Redis add-on thường thiết lập qua Railway CLI (`railway variables set`) hoặc Dashboard.
  - `render.yaml` dùng định dạng **YAML (Blueprint / Infrastructure as Code)**, khai báo được **cả stack nhiều service** trong một file (`services:` gồm web service `type: web`, `runtime: docker`, `healthCheckPath: /health`, lẫn managed Redis/Key Value) và hỗ trợ khai báo biến môi trường an toàn ngay trong file (`generateValue: true` hoặc `sync: false` cho secret).

### Exercise 3.3: Tóm tắt pipeline CI/CD Cloud Run (`03-cloud-deployment/production-cloud-run/`)

1. Đọc `cloudbuild.yaml`: Pipeline Cloud Build gồm 4 bước tuần tự (`waitFor`): (1) `test` chạy `pytest tests/ -v` trong `python:3.11-slim`; (2) `build` dựng Docker image gắn tag `$COMMIT_SHA` và `:latest` (tận dụng `--cache-from`); (3) `push` đẩy image lên Container Registry (`gcr.io/$PROJECT_ID/ai-agent`); (4) `deploy` chạy `gcloud run deploy` triển khai lên Cloud Run (`asia-southeast1`, `min-instances=1`, `max-instances=10`, lấy secret từ Secret Manager).
2. `service.yaml` khai báo Service Knative/Cloud Run dạng IaC: cấu hình concurrency (`80`), giới hạn CPU/RAM (`1 vCPU / 512Mi`), `secretKeyRef` cho `OPENAI_API_KEY` và `AGENT_API_KEY`, cùng `livenessProbe` (`/health`) và `startupProbe` (`/ready`).

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/`)

- Không có `X-API-Key` → **HTTP 401**:

```http
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
```

- Có `X-API-Key` hợp lệ → **HTTP 200**:

```http
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

### Exercise 4.2 – 4.3: JWT (`POST /auth/token`) & Rate Limiting (`04-api-gateway/production/`)

- Đăng nhập `student` / `demo123` tại `POST /auth/token` để lấy JWT (`Bearer <REDACTED_TOKEN>`).
- Gọi `POST /ask` hợp lệ lần đầu (`200 OK`, `requests_remaining: 9`):

```http
HTTP/1.1 200 OK
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"question":"what is docker?","answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}
```

- Vòng lặp 12 request liên tiếp (`student` giới hạn 10 req/phút, cộng 1 request trước đó nên từ Request 10 trong vòng lặp bị chặn **429 Too Many Requests**):

```text
Request 1..9: HTTP 200
Request 10: HTTP 429 -> {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
Request 11: HTTP 429 -> {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
Request 12: HTTP 429 -> {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

```http
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
retry-after: 59
content-type: application/json

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Cost Guard

- Rate limit chỉ chặn tần suất gọi (`req/phút`), còn Cost Guard kiểm soát tổng chi phí USD theo token (`input_tokens`, `output_tokens`) để tránh vượt ngân sách ngay cả khi request đi chậm dưới ngưỡng rate limit.
- Luồng chuẩn: `check_budget()` kiểm tra tổng chi tiêu hiện tại trong Redis trước khi gọi LLM (nếu `>= budget` → trả `HTTP 402`), sau khi LLM trả lời thì `record_cost()` tính chi phí theo đơn giá/1K token và cộng dồn vào Redis bằng `INCRBYFLOAT` kèm `EXPIRE` theo ngày/tháng.

---

## Part 5: Scaling & Reliability

### Exercise 5.1 – 5.2: Health Check, Readiness & Graceful Shutdown (`05-scaling-reliability/develop/`)

- `/health` (liveness) trả `200 OK` khi process còn sống (`status`, `uptime_seconds`, `checks`); `/ready` (readiness) trả `200 OK` (`{"ready":true,"in_flight_requests":1}`) khi sẵn sàng nhận traffic và trả `503` khi đang shutdown hoặc mất dependency.
- Khi gửi request `POST /ask?question=hello` (mock delay) và gửi `kill -SIGTERM <PID>` sau `0.5s`, request đang xử lý vẫn hoàn tất **HTTP 200** trước khi server đóng:

```text
In-flight /ask HTTP 200
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
INFO:     Shutting down
INFO:     127.0.0.1:36656 - "POST /ask?question=hello HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
2026-11-25 20:31:55,012 INFO 🔄 Graceful shutdown initiated...
2026-11-25 20:31:55,012 INFO ✅ Shutdown complete
```

### Exercise 5.3 – 5.5: Stateless + Redis + Nginx (`--scale agent=3`)

Chạy `docker compose -p k5-day14-scaling up -d --build --scale agent=3` và `python test_stateless.py` (cổng `8080`, `POST /chat`):

```text
Total requests: 5
Instances used: {'instance-2c8e12', 'instance-77ba74', 'instance-93c8f7'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

Nginx điều phối round-robin qua 3 instance khác nhau nhưng lịch sử hội thoại 10 message vẫn đầy đủ vì toàn bộ session state lưu tập trung trong Redis thay vì RAM cục bộ của từng container.

---

## Part 6: Final Project (`06-lab-complete/`)

Chạy `python check_production_ready.py` trong `Ubuntu-24.04` WSL2 (`posix`):

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 42/42 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

- Image size đo được: **201 MB** (`docker stop`: exit code `0`, `0.8s`).

---

## AI Log

- **Phiên làm việc (2026-11-25):**
  - *Hỏi gì:* Phân tích cấu trúc repo Day 14, thiết kế lộ trình `CP0 → CP8`, và hướng dẫn/thực thi hoàn thiện repo.
  - *Nhận gì:* Phân tích chi tiết 7 phần, phát hiện ràng buộc WSL2 (`os.name == "nt"` trên Windows không test được `SIGTERM`), thiết kế hệ thống và kế hoạch 8 task.
  - *Tự sửa & tự kiểm tra:* Đã tự kiểm tra các lệnh chạy thực tế của Part 1, Part 4, Part 5 `develop` trong `Ubuntu-24.04` WSL2 và đối chiếu từng output HTTP trước khi ghi vào bài.
