"""
prompt_templates 테이블.
프롬프트를 코드처럼 버전 관리한다.

사용법:
  - category로 용도를 구분 (analyze | regenerate | route)
  - is_active=True인 것만 서비스에서 사용
  - 새 버전을 만들 때 기존 것 is_active=False, 새 것 is_active=True

면접 포인트:
  "프롬프트도 배포 단위로 관리했습니다. 버전 필드로 어떤 프롬프트가
   어떤 결과를 만들었는지 추적 가능하고, A/B 테스트 확장도 가능합니다."
"""
import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, Enum as SAEnum, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class PromptCategory(str, enum.Enum):
    analyze = "analyze"        # 티켓 분석 (분류 + 요약 + 답변초안)
    regenerate = "regenerate"  # 답변 재생성만
    route = "route"            # 담당 부서 추천만


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)   # e.g. "v1.0", "v1.1"
    category: Mapped[PromptCategory] = mapped_column(
        SAEnum(PromptCategory), nullable=False, index=True
    )
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    # {title}, {content} 같은 플레이스홀더를 .format()으로 채운다

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)  # 변경 이유 메모

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<PromptTemplate {self.category} {self.version} active={self.is_active}>"
