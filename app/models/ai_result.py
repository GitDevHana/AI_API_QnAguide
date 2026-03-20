"""
ai_results 테이블.
- AI가 분석한 결과를 raw_json + 파싱된 필드 모두 저장한다.
- ticket 하나에 여러 개 생길 수 있음 (재생성 포함).
- latest_only 쿼리는 ticket_id + created_at DESC + LIMIT 1 로 가져온다.
"""
import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import String, Text, Float, Integer, DateTime, Enum as SAEnum, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class UrgencyLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class SentimentType(str, enum.Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"


class SuggestedTeam(str, enum.Enum):
    payments = "payments"
    tech = "tech"
    ops = "ops"
    support = "support"
    unknown = "unknown"


class AIResult(Base):
    __tablename__ = "ai_results"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    ticket_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tickets.id"), nullable=False, index=True
    )

    # 파싱된 결과 필드
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=True)
    urgency: Mapped[UrgencyLevel] = mapped_column(
        SAEnum(UrgencyLevel), default=UrgencyLevel.medium, nullable=True
    )
    sentiment: Mapped[SentimentType] = mapped_column(
        SAEnum(SentimentType), default=SentimentType.neutral, nullable=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    suggested_team: Mapped[SuggestedTeam] = mapped_column(
        SAEnum(SuggestedTeam), default=SuggestedTeam.unknown, nullable=True
    )
    draft_reply: Mapped[str] = mapped_column(Text, nullable=True)

    # confidence: 모델이 직접 0~1 float 로 출력하게 프롬프트에서 강제
    # 면접 질문 "이 값 어떻게 나와요?" → "프롬프트에서 JSON 필드로 요청, 
    #   모델이 자체 확신도를 0.0~1.0으로 평가해 반환하게 했습니다.
    #   실제 calibration은 향후 레이블 데이터 쌓이면 후처리로 보정 가능합니다."
    confidence: Mapped[float] = mapped_column(Float, nullable=True)

    # 원본 JSON 그대로 보존 (디버깅, 재파싱용)
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=True)

    # 어떤 프롬프트 버전을 썼는지 추적
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

    # Relationships
    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="ai_results")

    def __repr__(self) -> str:
        return f"<AIResult ticket={self.ticket_id[:8]} urgency={self.urgency}>"
