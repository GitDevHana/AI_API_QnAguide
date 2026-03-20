"""
앱 전역 설정.
.env 파일을 읽어 타입 안전하게 제공한다.
"""
from pydantic_settings import BaseSettings
from pydantic import field_validator
from functools import lru_cache
from typing import Literal


class Settings(BaseSettings):
    # App
    app_env: Literal["development", "production"] = "development"
    debug: bool = True
    log_level: str = "INFO"

    # DB
    database_url: str

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # AI
    ai_provider: Literal["openai", "anthropic", "gemini"] = "gemini"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    ai_model: str = "gemini-2.5-flash-lite-preview-04-17"
    ai_timeout_seconds: int = 30
    ai_max_retries: int = 3

    # Rate limit
    rate_limit_per_minute: int = 60

    @field_validator("database_url")
    @classmethod
    def validate_db_url(cls, v: str) -> str:
        # asyncpg 드라이버 쓸 때는 postgresql+asyncpg:// 로 바꿔야 함
        # 지금은 sync SQLAlchemy 사용
        return v

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # .env에 정의되지 않은 변수 무시


@lru_cache()
def get_settings() -> Settings:
    """싱글턴 설정 객체. 앱 전체에서 이것만 쓴다."""
    return Settings()


settings = get_settings()
