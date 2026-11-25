# Deployment Information

## Public URL
https://k5-l3a-day14-phamviethung-2a202603370.onrender.com

## Platform
Render (Docker Web Service + Render Key Value / Redis Free, region Singapore)

## Test Commands

### Health & Readiness Check
```bash
export BASE="https://k5-l3a-day14-phamviethung-2a202603370.onrender.com"

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"   # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"    # 200
```

### API Test (Authentication & Inference)
```bash
# Không có API key → 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'

# Có API key → 200
curl -X POST "$BASE/ask" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "What is deployment?"}'
```

**Observed output (`2026-11-25`):**
```text
1. GET /health -> 200
2. GET /ready -> 200
3. POST /ask (no key) -> 401
4. POST /ask (with X-API-Key) -> 200
{"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","usage":{"input_tokens":4,"output_tokens":19,"cost_usd":1.2e-05}}
```

## Environment Variables Set (on Render Dashboard)
- `ENVIRONMENT=production`
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`
- `MONTHLY_BUDGET_USD=10.0`
- `REDIS_URL` (Internal Redis URL của service `k5-day14-redis`)
- `AGENT_API_KEY` (đặt trực tiếp trên Render Dashboard, không commit vào Git)
- `PORT` (Render tự inject, app lắng nghe `10000`)

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running logs](screenshots/running.png)
- [Public endpoint test](screenshots/test.png)
