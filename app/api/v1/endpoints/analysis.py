"""
AI 분석 엔드포인트.
POST /api/v1/tickets/{id}/analyze            - AI 분석 실행 (비동기)
GET  /api/v1/tickets/{id}/analysis           - 최신 분석 결과 조회
POST /api/v1/tickets/{id}/regenerate-draft   - 답변 초안 재생성
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.models.user import User, UserRole
from app.models.ticket import Ticket, TicketStatus
from app.models.ai_result import AIResult
from app.schemas.ai_result import AIAnalysisResponse, RegenerateDraftRequest
from app.api.deps import get_current_user
from app.services import ticket_ai_service
from app.core.logging import logger

router = APIRouter(tags=["analysis"])


def _check_ticket_access(ticket_id: str, db: Session, current_user: User) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    if not ticket or ticket.is_deleted:
        raise HTTPException(status_code=404, detail="티켓을 찾을 수 없습니다")
    if current_user.role == UserRole.user and ticket.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다")
    return ticket


@router.post("/tickets/{ticket_id}/analyze", status_code=202)
def trigger_analysis(
    ticket_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    AI 분석을 백그라운드로 실행한다.
    즉시 202 Accepted 반환 → 결과는 GET /analysis로 폴링하거나
    향후 WebSocket / webhook으로 확장 가능.

    BackgroundTasks → Celery 전환 시:
      background_tasks.add_task(...) 대신
      analyze_ticket_task.delay(ticket_id) 로 바꾸면 끝.
    """
    ticket = _check_ticket_access(ticket_id, db, current_user)

    if ticket.status == TicketStatus.analyzing:
        raise HTTPException(status_code=409, detail="이미 분석 중입니다")

    # DB 세션을 백그라운드로 넘기면 안 됨 → ticket_id만 넘기고 내부에서 새 세션 사용
    # 주의: BackgroundTasks는 같은 프로세스 내에서 실행됨
    # 실제 트래픽이 붙으면 Celery로 전환하는 것을 권장
    from app.db.base import SessionLocal

    def run_analysis():
        bg_db = SessionLocal()
        try:
            ticket_ai_service.analyze_ticket(ticket_id, bg_db)
        except Exception as e:
            logger.error("background_analyze_failed", ticket_id=ticket_id, error=str(e))
        finally:
            bg_db.close()

    background_tasks.add_task(run_analysis)

    return {"message": "분석이 시작되었습니다", "ticket_id": ticket_id, "status": "analyzing"}


@router.get("/tickets/{ticket_id}/analysis", response_model=AIAnalysisResponse)
def get_analysis(
    ticket_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """최신 AI 분석 결과 반환."""
    _check_ticket_access(ticket_id, db, current_user)

    result = (
        db.query(AIResult)
        .filter(AIResult.ticket_id == ticket_id)
        .order_by(AIResult.created_at.desc())
        .first()
    )
    if not result:
        raise HTTPException(status_code=404, detail="분석 결과가 없습니다. 먼저 /analyze를 실행해주세요")
    return result


@router.post("/tickets/{ticket_id}/regenerate-draft", response_model=AIAnalysisResponse)
def regenerate_draft(
    ticket_id: str,
    payload: RegenerateDraftRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """답변 초안 재생성. 추가 지시사항(instruction) 선택 입력."""
    _check_ticket_access(ticket_id, db, current_user)
    try:
        result = ticket_ai_service.regenerate_draft(
            ticket_id=ticket_id,
            db=db,
            instruction=payload.instruction,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result
