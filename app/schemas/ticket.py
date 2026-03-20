from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional
from app.models.ticket import TicketStatus, TicketCategory


class TicketCreate(BaseModel):
    title: str
    content: str

    @field_validator("title")
    @classmethod
    def title_length(cls, v: str) -> str:
        if len(v.strip()) < 5:
            raise ValueError("제목은 5자 이상 입력해주세요")
        if len(v) > 500:
            raise ValueError("제목은 500자를 넘을 수 없습니다")
        return v.strip()

    @field_validator("content")
    @classmethod
    def content_length(cls, v: str) -> str:
        # 너무 긴 입력은 AI 비용 낭비 + prompt injection 위험
        if len(v.strip()) < 10:
            raise ValueError("내용은 10자 이상 입력해주세요")
        if len(v) > 5000:
            raise ValueError("내용은 5000자를 넘을 수 없습니다")
        return v.strip()


class TicketUpdate(BaseModel):
    status: Optional[TicketStatus] = None
    category: Optional[TicketCategory] = None   # 관리자 수동 수정용


class TicketResponse(BaseModel):
    id: str
    user_id: str
    title: str
    content: str
    status: TicketStatus
    category: TicketCategory
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TicketListResponse(BaseModel):
    tickets: list[TicketResponse]
    total: int
    page: int
    page_size: int
