"""
티켓 엔드포인트.
POST   /api/v1/tickets              - 문의 등록
GET    /api/v1/tickets              - 목록 조회 (필터/페이징)
GET    /api/v1/tickets/{id}         - 상세 조회
PATCH  /api/v1/tickets/{id}         - 상태/카테고리 수정 (관리자/상담원)
DELETE /api/v1/tickets/{id}         - soft delete (본인 또는 관리자)
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.db.base import get_db
from app.models.user import User, UserRole
from app.models.ticket import Ticket, TicketStatus, TicketCategory
from app.schemas.ticket import TicketCreate, TicketUpdate, TicketResponse, TicketListResponse
from app.api.deps import get_current_user, require_agent_or_above
from app.models.logs import AuditLog

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _get_ticket_or_404(ticket_id: str, db: Session) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    if not ticket or ticket.is_deleted:
        raise HTTPException(status_code=404, detail="티켓을 찾을 수 없습니다")
    return ticket


@router.post("", response_model=TicketResponse, status_code=201)
def create_ticket(
    payload: TicketCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = Ticket(
        user_id=current_user.id,
        title=payload.title,
        content=payload.content,
    )
    db.add(ticket)
    db.flush()

    # 생성 감사 로그
    db.add(AuditLog(
        ticket_id=ticket.id,
        action="ticket_created",
        actor_id=current_user.id,
        actor_email=current_user.email,
    ))
    db.commit()
    db.refresh(ticket)
    return ticket


@router.get("", response_model=TicketListResponse)
def list_tickets(
    status: Optional[TicketStatus] = Query(None),
    category: Optional[TicketCategory] = Query(None),
    urgency: Optional[str] = Query(None),          # ai_results.urgency 필터는 서비스 레이어로
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Ticket).filter(Ticket.is_deleted == False)

    # 일반 유저는 본인 티켓만
    if current_user.role == UserRole.user:
        query = query.filter(Ticket.user_id == current_user.id)

    if status:
        query = query.filter(Ticket.status == status)
    if category:
        query = query.filter(Ticket.category == category)

    total = query.count()
    tickets = (
        query.order_by(Ticket.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return TicketListResponse(tickets=tickets, total=total, page=page, page_size=page_size)


@router.get("/{ticket_id}", response_model=TicketResponse)
def get_ticket(
    ticket_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = _get_ticket_or_404(ticket_id, db)
    # 일반 유저는 본인 티켓만
    if current_user.role == UserRole.user and ticket.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다")
    return ticket


@router.patch("/{ticket_id}", response_model=TicketResponse)
def update_ticket(
    ticket_id: str,
    payload: TicketUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_agent_or_above),
):
    ticket = _get_ticket_or_404(ticket_id, db)
    old_values = {}

    if payload.status is not None:
        old_values["status"] = ticket.status
        ticket.status = payload.status
    if payload.category is not None:
        old_values["category"] = ticket.category
        ticket.category = payload.category

    db.add(AuditLog(
        ticket_id=ticket.id,
        action="ticket_updated",
        actor_id=current_user.id,
        actor_email=current_user.email,
        meta={"before": {k: v.value for k, v in old_values.items()},
                  "after": payload.model_dump(exclude_none=True)},
    ))
    db.commit()
    db.refresh(ticket)
    return ticket


@router.delete("/{ticket_id}", status_code=204)
def delete_ticket(
    ticket_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = _get_ticket_or_404(ticket_id, db)
    if current_user.role == UserRole.user and ticket.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다")

    ticket.is_deleted = True
    db.add(AuditLog(
        ticket_id=ticket.id,
        action="ticket_deleted",
        actor_id=current_user.id,
        actor_email=current_user.email,
    ))
    db.commit()
