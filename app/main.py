"""
FastAPI 앱 진입점.
- 라우터 등록
- 미들웨어 설정 (CORS, request_id, rate limit)
- 전역 예외 핸들러
- 헬스체크
"""
import uuid
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import router as v1_router
from app.core.config import settings
from app.core.logging import setup_logging, logger
from app.db.base import engine, Base

# 모든 모델 임포트 (Alembic이 인식하게)
import app.models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 시작 시
    setup_logging()
    logger.info("app_starting", env=settings.app_env, provider=settings.ai_provider)
    # 테이블 자동 생성 (개발용 - 운영에선 alembic migrate 사용)
    if settings.app_env == "development":
        Base.metadata.create_all(bind=engine)
    yield
    # 종료 시
    logger.info("app_shutting_down")


app = FastAPI(
    title="AI_API_QnAguide",
    description="고객 문의 자동 분류·요약·답변초안 생성 백엔드 서비스",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.debug else ["https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request ID 미들웨어 ───────────────────────────
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    start = time.time()

    # 응답 헤더에 request_id 포함
    response: Response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time"] = str(round((time.time() - start) * 1000)) + "ms"
    return response


# ── 전역 예외 핸들러 ──────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"detail": "서버 내부 오류가 발생했습니다. 잠시 후 다시 시도해주세요."},
    )


# ── 라우터 등록 ───────────────────────────────────
app.include_router(v1_router)


# ── 헬스체크 ──────────────────────────────────────
@app.get("/health", tags=["system"])
def health_check():
    return {
        "status": "ok",
        "env": settings.app_env,
        "ai_provider": settings.ai_provider,
        "model": settings.ai_model,
    }


@app.get("/", tags=["system"])
def root():
    return {"message": "AI_API_QnAguide", "docs": "/docs"}
