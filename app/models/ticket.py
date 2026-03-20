"""
tickets 테이블.
status 흐름: open → analyzing → analyzed → resolved | closed
"""
import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, Enum as SAEnum, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class TicketStatus(str, enum.Enum):
    open = "open"
    analyzing = "analyzing"      # AI 분석 진행 중
    analyzed = "analyzed"        # AI 분석 완료, 상담원 검토 대기
    resolved = "resolved"
    closed = "closed"


class TicketCategory(str, enum.Enum):
    billing = "billing"
    bug = "bug"
    account = "account"
    refund = "refund"
    abuse = "abuse"
    other = "other"
    unknown = "unknown"          # 분류 전 초기값


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TicketStatus] = mapped_column(
        SAEnum(TicketStatus), default=TicketStatus.open, nullable=False, index=True
    )
    category: Mapped[TicketCategory] = mapped_column(
        SAEnum(TicketCategory), default=TicketCategory.unknown, nullable=False, index=True
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)  # soft delete
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="tickets")
    ai_results: Mapped[list["AIResult"]] = relationship(
        "AIResult", back_populates="ticket", order_by="AIResult.created_at.desc()"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship("AuditLog", back_populates="ticket")

    def __repr__(self) -> str:
        return f"<Ticket {self.id[:8]} [{self.status}]>"
