"""
Celery 워커.
현재는 BackgroundTasks로 돌아가지만,
트래픽이 붙으면 아래 task들을 .delay()로 호출하면 끝.

전환 방법:
  Before: background_tasks.add_task(run_analysis)
  After:  analyze_ticket_task.delay(ticket_id)
"""
from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "copilot",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Seoul",
    task_track_started=True,
    task_acks_late=True,           # 작업 완료 후 ack (재시도 안전)
    worker_prefetch_multiplier=1,  # AI 호출은 느리니까 한 번에 하나씩
)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=5)
def analyze_ticket_task(self, ticket_id: str):
    """AI 분석 Celery 태스크."""
    from app.db.base import SessionLocal
    from app.services import ticket_ai_service

    db = SessionLocal()
    try:
        ticket_ai_service.analyze_ticket(ticket_id, db)
    except Exception as exc:
        db.close()
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3)
def regenerate_draft_task(self, ticket_id: str, instruction: str = None):
    """답변 재생성 Celery 태스크."""
    from app.db.base import SessionLocal
    from app.services import ticket_ai_service

    db = SessionLocal()
    try:
        ticket_ai_service.regenerate_draft(ticket_id, db, instruction)
    except Exception as exc:
        db.close()
        raise self.retry(exc=exc)
    finally:
        db.close()
