# Alembic이 모든 모델을 인식하려면 여기서 임포트해야 한다
from app.models.user import User, UserRole
from app.models.ticket import Ticket, TicketStatus, TicketCategory
from app.models.ai_result import AIResult, UrgencyLevel, SentimentType, SuggestedTeam
from app.models.prompt_template import PromptTemplate, PromptCategory
from app.models.logs import AuditLog, ModelUsageLog

__all__ = [
    "User", "UserRole",
    "Ticket", "TicketStatus", "TicketCategory",
    "AIResult", "UrgencyLevel", "SentimentType", "SuggestedTeam",
    "PromptTemplate", "PromptCategory",
    "AuditLog", "ModelUsageLog",
]
