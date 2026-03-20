from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from app.models.ai_result import UrgencyLevel, SentimentType, SuggestedTeam


class AIAnalysisResponse(BaseModel):
    ticket_id: str
    category: Optional[str]
    urgency: Optional[UrgencyLevel]
    sentiment: Optional[SentimentType]
    summary: Optional[str]
    suggested_team: Optional[SuggestedTeam]
    draft_reply: Optional[str]
    confidence: Optional[float]
    model_name: str
    prompt_version: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class RegenerateDraftRequest(BaseModel):
    """답변 재생성 시 추가 지시사항 (선택)"""
    instruction: Optional[str] = None   # 예: "더 공손하게", "영어로"
