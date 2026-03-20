"""
티켓 AI 분석 서비스.
- AI 호출 → 결과 저장 → 비용 로그 → 티켓 상태 업데이트를 하나의 트랜잭션으로 묶는다.
- BackgroundTasks로 비동기 실행 (Celery 전환 시 이 함수를 task로 감싸면 됨)
"""
from sqlalchemy.orm import Session
from typing import Optional

from app.services.ai_provider import get_ai_provider
from app.models.ticket import Ticket, TicketStatus, TicketCategory
from app.models.ai_result import AIResult
from app.models.logs import ModelUsageLog, AuditLog
from app.models.prompt_template import PromptTemplate, PromptCategory
from app.core.config import settings
from app.core.logging import logger


def _get_active_prompt(db: Session, category: PromptCategory) -> tuple[Optional[str], Optional[str], str]:
    """
    DB에서 활성 프롬프트 템플릿 조회.
    없으면 (None, None, "default") 반환 → ai_provider가 기본값 사용
    """
    tmpl = (
        db.query(PromptTemplate)
        .filter(
            PromptTemplate.category == category,
            PromptTemplate.is_active == True,
        )
        .order_by(PromptTemplate.created_at.desc())
        .first()
    )
    if not tmpl:
        return None, None, "default"
    return tmpl.system_prompt, tmpl.user_prompt_template, tmpl.version


def analyze_ticket(ticket_id: str, db: Session) -> AIResult:
    """
    티켓 AI 분석 실행.
    - 티켓 상태: open → analyzing → analyzed
    - AI 결과 저장
    - 비용 로그 저장
    """
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise ValueError(f"티켓 없음: {ticket_id}")

    # 상태를 analyzing으로 변경
    ticket.status = TicketStatus.analyzing
    db.commit()

    provider = get_ai_provider()
    system_prompt, user_template, prompt_version = _get_active_prompt(
        db, PromptCategory.analyze
    )

    usage_log = ModelUsageLog(
        ticket_id=ticket_id,
        provider=settings.ai_provider,
        model=settings.ai_model,
        success=False,  # 실패 시 그대로 저장되도록 먼저 False
    )
    db.add(usage_log)

    try:
        result, usage = provider.analyze_ticket(
            title=ticket.title,
            content=ticket.content,
            system_prompt=system_prompt,
            user_template=user_template,
            prompt_version=prompt_version,
        )

        # AI 결과 저장
        ai_result = AIResult(
            ticket_id=ticket_id,
            model_name=settings.ai_model,
            category=result.category,
            urgency=result.urgency,
            sentiment=result.sentiment,
            summary=result.summary,
            suggested_team=result.suggested_team,
            draft_reply=result.draft_reply,
            confidence=result.confidence,
            raw_json=result.raw,
            prompt_version=prompt_version,
        )
        db.add(ai_result)

        # 티켓 카테고리 업데이트 (분류 결과 반영)
        try:
            ticket.category = TicketCategory(result.category)
        except ValueError:
            ticket.category = TicketCategory.other
        ticket.status = TicketStatus.analyzed

        # 비용 로그 업데이트
        usage_log.success = True
        usage_log.prompt_tokens = usage["prompt_tokens"]
        usage_log.completion_tokens = usage["completion_tokens"]
        usage_log.total_tokens = usage["total_tokens"]
        usage_log.estimated_cost_usd = usage["estimated_cost_usd"]
        usage_log.latency_ms = usage["latency_ms"]

        db.add(AuditLog(
            ticket_id=ticket_id,
            action="ticket_analyzed",
            meta={
                "model": settings.ai_model,
                "urgency": result.urgency,
                "category": result.category,
                "confidence": result.confidence,
                "cost_usd": usage["estimated_cost_usd"],
            },
        ))
        db.commit()
        db.refresh(ai_result)

        logger.info(
            "ticket_analyzed",
            ticket_id=ticket_id,
            urgency=result.urgency,
            latency_ms=usage["latency_ms"],
            cost_usd=usage["estimated_cost_usd"],
        )
        return ai_result

    except Exception as e:
        usage_log.success = False
        usage_log.error_message = str(e)
        ticket.status = TicketStatus.open  # 실패 시 원래대로 롤백
        db.commit()
        logger.error("analyze_failed", ticket_id=ticket_id, error=str(e))
        raise


def regenerate_draft(
    ticket_id: str,
    db: Session,
    instruction: Optional[str] = None,
) -> AIResult:
    """
    답변 초안 재생성.
    기존 최신 AIResult를 기반으로 draft_reply만 새로 생성.
    """
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise ValueError(f"티켓 없음: {ticket_id}")

    # 가장 최근 AI 결과 가져오기
    latest = (
        db.query(AIResult)
        .filter(AIResult.ticket_id == ticket_id)
        .order_by(AIResult.created_at.desc())
        .first()
    )
    if not latest:
        raise ValueError("분석 결과가 없습니다. 먼저 /analyze를 실행해주세요")

    provider = get_ai_provider()
    _, user_template, prompt_version = _get_active_prompt(db, PromptCategory.regenerate)

    new_draft = provider.regenerate_draft(
        title=ticket.title,
        content=ticket.content,
        previous_draft=latest.draft_reply or "",
        instruction=instruction,
    )

    # 새 AIResult row 생성 (기존 것 보존 + 재생성 이력 유지)
    new_result = AIResult(
        ticket_id=ticket_id,
        model_name=settings.ai_model,
        category=latest.category,
        urgency=latest.urgency,
        sentiment=latest.sentiment,
        summary=latest.summary,
        suggested_team=latest.suggested_team,
        draft_reply=new_draft,
        confidence=latest.confidence,
        raw_json={"regenerated": True, "instruction": instruction},
        prompt_version=f"{prompt_version}:regen",
    )
    db.add(new_result)
    db.add(AuditLog(
        ticket_id=ticket_id,
        action="draft_regenerated",
        meta={"instruction": instruction},
    ))
    db.commit()
    db.refresh(new_result)
    return new_result
