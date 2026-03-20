"""
관리자 전용 엔드포인트.
GET  /api/v1/admin/stats           - 전체 통계
GET  /api/v1/admin/urgent          - 긴급 티켓 목록
GET  /api/v1/admin/usage-logs      - AI 사용/비용 로그
POST /api/v1/admin/tickets/{id}/reanalyze  - 실패 티켓 재분석
"""
from fastapi import APIRouter, Depends, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from typing import Optional
from datetime import datetime, timezone, timedelta

from app.db.base import get_db, SessionLocal
from app.models.ticket import Ticket, TicketStatus, TicketCategory
from app.models.ai_result import AIResult, UrgencyLevel
from app.models.logs import ModelUsageLog
from app.api.deps import require_admin
from app.models.user import User
from app.services import ticket_ai_service
from app.core.logging import logger

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats")
def get_stats(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """최근 N일간 통계."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    total_tickets = db.query(Ticket).filter(
        Ticket.created_at >= since, Ticket.is_deleted == False
    ).count()

    # 상태별 카운트
    status_counts = dict(
        db.query(Ticket.status, func.count(Ticket.id))
        .filter(Ticket.created_at >= since, Ticket.is_deleted == False)
        .group_by(Ticket.status)
        .all()
    )

    # 카테고리별 카운트
    category_counts = dict(
        db.query(Ticket.category, func.count(Ticket.id))
        .filter(Ticket.created_at >= since, Ticket.is_deleted == False)
        .group_by(Ticket.category)
        .all()
    )

    # 긴급도별 카운트 (ai_results 기준)
    urgency_counts = dict(
        db.query(AIResult.urgency, func.count(AIResult.id))
        .filter(AIResult.created_at >= since)
        .group_by(AIResult.urgency)
        .all()
    )

    # AI 비용 합계
    cost_result = db.query(
        func.sum(ModelUsageLog.estimated_cost_usd),
        func.sum(ModelUsageLog.total_tokens),
        func.avg(ModelUsageLog.latency_ms),
        func.count(ModelUsageLog.id),
        func.sum(func.cast(~ModelUsageLog.success, int)),
    ).filter(ModelUsageLog.created_at >= since).first()

    total_cost, total_tokens, avg_latency, total_calls, failed_calls = cost_result

    return {
        "period_days": days,
        "tickets": {
            "total": total_tickets,
            "by_status": {k.value if hasattr(k, 'value') else k: v for k, v in status_counts.items()},
            "by_category": {k.value if hasattr(k, 'value') else k: v for k, v in category_counts.items()},
        },
        "ai_analysis": {
            "by_urgency": {k.value if hasattr(k, 'value') else k: v for k, v in urgency_counts.items()},
        },
        "ai_usage": {
            "total_calls": total_calls or 0,
            "failed_calls": int(failed_calls or 0),
            "total_tokens": int(total_tokens or 0),
            "total_cost_usd": round(float(total_cost or 0), 4),
            "avg_latency_ms": int(avg_latency or 0),
        },
    }


@router.get("/urgent")
def get_urgent_tickets(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """긴급(high urgency) 티켓 + 최신 AI 결과."""
    # AIResult 서브쿼리: 티켓당 최신 결과 1개
    subq = (
        db.query(
            AIResult.ticket_id,
            func.max(AIResult.created_at).label("latest"),
        )
        .filter(AIResult.urgency == UrgencyLevel.high)
        .group_by(AIResult.ticket_id)
        .subquery()
    )

    rows = (
        db.query(Ticket, AIResult)
        .join(subq, Ticket.id == subq.c.ticket_id)
        .join(
            AIResult,
            and_(
                AIResult.ticket_id == subq.c.ticket_id,
                AIResult.created_at == subq.c.latest,
            ),
        )
        .filter(Ticket.is_deleted == False, Ticket.status != TicketStatus.resolved)
        .order_by(Ticket.created_at.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "ticket_id": t.id,
            "title": t.title,
            "status": t.status,
            "created_at": t.created_at,
            "urgency": r.urgency,
            "category": r.category,
            "summary": r.summary,
            "suggested_team": r.suggested_team,
        }
        for t, r in rows
    ]


@router.get("/usage-logs")
def get_usage_logs(
    days: int = Query(7),
    success_only: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """AI 호출 이력 + 비용 로그."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = db.query(ModelUsageLog).filter(ModelUsageLog.created_at >= since)
    if success_only:
        query = query.filter(ModelUsageLog.success == True)

    total = query.count()
    logs = (
        query.order_by(ModelUsageLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "logs": [
            {
                "id": l.id,
                "ticket_id": l.ticket_id,
                "model": l.model,
                "tokens": l.total_tokens,
                "cost_usd": l.estimated_cost_usd,
                "latency_ms": l.latency_ms,
                "success": l.success,
                "error": l.error_message,
                "created_at": l.created_at,
            }
            for l in logs
        ],
    }


@router.post("/tickets/{ticket_id}/reanalyze", status_code=202)
def reanalyze_ticket(
    ticket_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """실패하거나 오분류된 티켓 재분석."""
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="티켓을 찾을 수 없습니다")

    def run():
        bg_db = SessionLocal()
        try:
            ticket_ai_service.analyze_ticket(ticket_id, bg_db)
        except Exception as e:
            logger.error("reanalyze_failed", ticket_id=ticket_id, error=str(e))
        finally:
            bg_db.close()

    background_tasks.add_task(run)
    return {"message": "재분석이 시작되었습니다", "ticket_id": ticket_id}
