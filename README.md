# AI_API_QnAguide

고객 문의를 자동으로 분류 · 요약 · 긴급도 판단 · 답변 초안 생성 · 담당 부서 추천까지 처리하는 AI 백엔드 서비스입니다.


---

## 핵심 기능

| 기능 | 설명 |
|---|---|
| 티켓 등록/조회/수정/삭제 | soft delete, 상태 흐름 관리 |
| AI 분석 (비동기) | 분류, 요약, 긴급도, 감정, 담당 부서 추천, 답변 초안 |
| 답변 재생성 | 추가 지시사항(더 공손하게, 영어로 등) 지원 |
| 프롬프트 버전 관리 | DB에서 프롬프트를 코드처럼 배포·롤백 |
| 관리자 대시보드 | 긴급 티켓 필터, 통계, 재분석 |
| AI 비용 추적 | 토큰 수, 지연시간, 예상 비용 per 호출 로깅 |
| JWT 인증 + RBAC | admin / agent / user 3단계 권한 |

---

## 기술 스택

| 영역 | 기술 |
|---|---|
| Backend | FastAPI 0.111 |
| DB | PostgreSQL 15 + SQLAlchemy 2.0 |
| 마이그레이션 | Alembic |
| 인증 | JWT (python-jose) + bcrypt |
| 비동기 | FastAPI BackgroundTasks → Celery + Redis (전환 가능) |
| AI | Anthropic Claude / OpenAI (provider 교체 가능 구조) |
| HTTP / Retry | httpx + tenacity |
| 로깅 | structlog (JSON 구조화) |
| 컨테이너 | Docker Compose |
| 테스트 | pytest + httpx TestClient |

---

## 아키텍처

```
Client
  │
  ▼
FastAPI (app/main.py)
  ├── /api/v1/auth          회원가입, 로그인, JWT
  ├── /api/v1/tickets       티켓 CRUD
  ├── /api/v1/tickets/{id}/analyze       AI 분석 트리거 (202 + BackgroundTask)
  ├── /api/v1/tickets/{id}/analysis      결과 조회
  ├── /api/v1/tickets/{id}/regenerate-draft  답변 재생성
  └── /api/v1/admin         통계, 긴급 목록, 비용 로그
         │
         ▼
  AIProvider (추상화)
  ├── AnthropicProvider
  └── OpenAIProvider
         │
         ▼
  PostgreSQL
  ├── users
  ├── tickets
  ├── ai_results        (분석 이력 전체 보존)
  ├── prompt_templates  (프롬프트 버전 관리)
  ├── audit_logs        (행동 이력)
  └── model_usage_logs  (비용 추적)
```

---

## ERD (주요 관계)

```
users ──< tickets ──< ai_results
                 └──< audit_logs
model_usage_logs  (ticket_id 참조, 독립 집계 가능)
prompt_templates  (ai_results.prompt_version 으로 추적)
```

---

## 빠른 시작

### 1. 환경변수 설정

```bash
cp .env.example .env
```

### 2. 실행 (Docker Compose)

```bash
docker compose up -d
```

컨테이너 3개가 뜹니다: `copilot_db` (PostgreSQL), `copilot_redis`, `copilot_api`

### 3. 테이블 생성 + 시드 데이터

```bash
# 개발 환경에서는 앱 시작 시 자동으로 테이블 생성됨
# 시드 데이터 (샘플 계정 + 티켓 30개)
docker compose exec api python scripts/seed_data.py
```

시드 후 생성되는 계정:

| role | email | password |
|---|---|---|
| admin | admin@example.com | admin1234! |
| agent | agent@example.com | agent1234! |
| user | user@example.com | user1234! |

### 4. Swagger UI

```
http://localhost:8000/docs
```

---

## API 주요 흐름

### 티켓 등록 → AI 분석 → 결과 조회

```bash
# 1. 로그인
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"user1234!"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2. 티켓 등록
TICKET_ID=$(curl -s -X POST http://localhost:8000/api/v1/tickets \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"결제가 두 번 됐어요","content":"어제 카드로 결제했는데 오늘 또 결제 문자가 왔습니다. 환불 부탁드립니다."}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 3. AI 분석 트리거 (202 즉시 반환)
curl -s -X POST http://localhost:8000/api/v1/tickets/$TICKET_ID/analyze \
  -H "Authorization: Bearer $TOKEN"

# 4. 결과 조회 (3초 후)
curl -s http://localhost:8000/api/v1/tickets/$TICKET_ID/analysis \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

예상 응답:

```json
{
  "ticket_id": "...",
  "category": "billing",
  "urgency": "high",
  "sentiment": "negative",
  "summary": "사용자가 중복 결제를 주장하며 환불 또는 확인을 요청함",
  "suggested_team": "payments",
  "draft_reply": "안녕하세요. 결제 내역을 즉시 확인하겠습니다...",
  "confidence": 0.91,
  "model_name": "claude-3-5-haiku-20241022",
  "prompt_version": "v1.0"
}
```

### 답변 재생성

```bash
curl -X POST http://localhost:8000/api/v1/tickets/$TICKET_ID/regenerate-draft \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"instruction": "더 공손하게, 구체적인 처리 기한을 포함해서"}'
```

---

## AI 프롬프트 전략

### JSON 구조화 강제

모델에게 반드시 JSON으로만 응답하게 강제하고, 마크다운 코드블록으로 감싸는 경우도 방어 처리합니다.

```python
# ai_provider.py 의 파싱 방어 로직
clean = raw_text.strip()
if clean.startswith("```"):
    lines = clean.split("\n")
    clean = "\n".join(lines[1:-1])
try:
    parsed = json.loads(clean)
except json.JSONDecodeError:
    parsed = {"summary": raw_text[:500], "confidence": 0.1}  # 폴백
```

### confidence 값

모델이 JSON 필드로 자체 확신도(`0.0~1.0`)를 직접 출력하게 프롬프트에서 요청합니다.
향후 레이블 데이터가 충분히 쌓이면 calibration 후처리로 보정할 수 있는 구조입니다.

### 프롬프트 버전 관리

`prompt_templates` 테이블에서 활성 프롬프트를 관리합니다.
새 버전 배포 시 기존 버전을 `is_active=False`로 바꾸고 새 버전을 삽입하면
코드 배포 없이 프롬프트가 교체됩니다.

```sql
-- 현재 활성 프롬프트 확인
SELECT version, category, is_active, created_at FROM prompt_templates ORDER BY created_at DESC;

-- 새 버전으로 교체
UPDATE prompt_templates SET is_active = false WHERE category = 'analyze';
INSERT INTO prompt_templates (version, category, system_prompt, ..., is_active)
VALUES ('v1.1', 'analyze', '개선된 프롬프트...', ..., true);
```

---

## 비용 최적화 전략

1. **저렴한 모델 기본 사용**: `claude-3-5-haiku` (분석), 재생성만 필요 시 동일 모델
2. **입력 길이 제한**: 티켓 content 최대 5000자, 초과 시 422 반환
3. **raw_json 보존**: 실패 시 재파싱 가능, 재호출 불필요
4. **비용 로그 집계**: `/api/v1/admin/stats`에서 기간별 총비용 확인 가능

---

## 비동기 처리 전환 가이드

현재는 `FastAPI BackgroundTasks`로 동작합니다.
트래픽이 붙으면 아래처럼 Celery로 전환할 수 있습니다.

```python
# Before (analysis.py)
background_tasks.add_task(run_analysis)

# After (Celery로 전환 시)
from app.workers.celery_worker import analyze_ticket_task
analyze_ticket_task.delay(ticket_id)
```

Celery 태스크는 `app/workers/celery_worker.py`에 이미 작성되어 있습니다.

---

## 로컬 개발 (Docker 없이)

```bash
# 가상환경
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# PostgreSQL, Redis는 별도 실행 필요
# .env의 DATABASE_URL, REDIS_URL을 localhost로 수정

uvicorn app.main:app --reload
```

---

## 테스트 실행

```bash
# Docker 안에서
docker compose exec api pytest

# 로컬에서
pytest tests/

# 커버리지 포함
pytest --cov=app --cov-report=html
```

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `analyze` 후 결과가 없음 | BackgroundTask가 아직 실행 중 | 2~3초 후 재조회 |
| `confidence`가 항상 0.5 | 모델이 JSON을 안 지킴 | raw_json 확인 후 프롬프트 수정 |
| 401 Unauthorized | 토큰 만료 (기본 60분) | 재로그인 |
| DB 연결 실패 | Docker 컨테이너 순서 | `db` healthcheck 확인 |
| AI 호출 timeout | 네트워크 또는 모델 응답 지연 | `AI_TIMEOUT_SECONDS` 늘리기 |

---

## 이력서 한 줄 요약

> FastAPI, PostgreSQL, Redis 기반으로 고객 문의 관리 시스템을 구현하고, AI API를 연동해 문의 분류·요약·긴급도 판단·답변 초안 생성을 자동화했습니다. 비동기 작업, JWT 인증, 프롬프트 버전 관리, AI 사용 비용 추적, 관리자 리뷰 기능을 포함해 운영 가능한 형태로 설계했습니다.
