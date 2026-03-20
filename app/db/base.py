"""
DB 연결 설정 및 세션 팩토리.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from typing import Generator

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,    # 끊긴 커넥션 자동 재연결
    pool_size=10,
    max_overflow=20,
    echo=settings.debug,   # SQL 로그 (개발 환경)
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """모든 모델이 상속하는 베이스 클래스."""
    pass


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI Depends로 주입되는 DB 세션.
    요청 하나당 세션 하나, 요청 끝나면 자동 close.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
