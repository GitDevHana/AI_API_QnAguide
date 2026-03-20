"""
AI 프로바이더 추상화 레이어.

설계 원칙:
  - AIProvider 인터페이스 하나로 provider 교체 가능
  - timeout / retry / 비용 로깅이 모든 구현체에 자동 적용
  - 프롬프트는 PromptTemplate DB에서 가져옴 (없으면 기본값 사용)

면접 포인트:
  "provider 교체 시 엔드포인트/서비스 코드를 건드리지 않고
   AIProvider 구현체만 바꾸면 됩니다. 전략 패턴입니다."
"""
import json
import time
from abc import ABC, abstractmethod
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.core.config import settings
from app.core.logging import logger


# ── 결과 데이터클래스 ─────────────────────────────
class AIAnalysisResult:
    def __init__(self, raw: dict):
        self.category: str = raw.get("category", "other")
        self.urgency: str = raw.get("urgency", "medium")
        self.sentiment: str = raw.get("sentiment", "neutral")
        self.summary: str = raw.get("summary", "")
        self.suggested_team: str = raw.get("suggested_team", "support")
        self.draft_reply: str = raw.get("draft_reply", "")
        # confidence: 모델이 자체 확신도를 0.0~1.0으로 평가해 반환
        # 향후 레이블 데이터 쌓이면 calibration 후처리로 보정 가능
        self.confidence: float = float(raw.get("confidence", 0.5))
        self.raw = raw

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "urgency": self.urgency,
            "sentiment": self.sentiment,
            "summary": self.summary,
            "suggested_team": self.suggested_team,
            "draft_reply": self.draft_reply,
            "confidence": self.confidence,
        }


# ── 기본 프롬프트 (DB에 없을 때 폴백) ─────────────
DEFAULT_SYSTEM_PROMPT = """당신은 고객 문의를 분석하는 전문 상담 AI입니다.
주어진 고객 문의를 분석하고 반드시 아래 JSON 형식으로만 응답하세요.
다른 텍스트, 마크다운 코드블록, 설명을 절대 포함하지 마세요.

응답 형식:
{
  "category": "billing|bug|account|refund|abuse|other 중 하나",
  "urgency": "low|medium|high 중 하나",
  "sentiment": "positive|neutral|negative 중 하나",
  "summary": "문의 내용 1~2문장 요약",
  "suggested_team": "payments|tech|ops|support|unknown 중 하나",
  "draft_reply": "고객에게 보낼 답변 초안 (200자 이내, 정중한 어투)",
  "confidence": 0.0~1.0 사이 숫자 (분석 확신도)
}

카테고리 기준:
- billing: 결제, 청구, 구독 관련
- bug: 기능 오류, 앱 문제
- account: 계정, 비밀번호, 로그인
- refund: 환불, 취소 요청
- abuse: 욕설, 스팸, 부적절한 내용
- other: 위에 해당하지 않는 경우

담당 부서 기준:
- payments: 결제/환불 관련
- tech: 기술적 버그/장애
- ops: 운영 정책, 계정 관리
- support: 일반 문의
"""

DEFAULT_USER_TEMPLATE = """제목: {title}

내용: {content}

위 고객 문의를 분석하고 JSON으로만 응답하세요."""


# ── 추상 인터페이스 ───────────────────────────────
class AIProvider(ABC):
    @abstractmethod
    def _call_api(self, system: str, user_msg: str) -> tuple[str, dict]:
        """
        (응답 텍스트, usage_info) 반환.
        usage_info: {"prompt_tokens": int, "completion_tokens": int}
        """
        ...

    def analyze_ticket(
        self,
        title: str,
        content: str,
        system_prompt: Optional[str] = None,
        user_template: Optional[str] = None,
        prompt_version: str = "default",
    ) -> tuple[AIAnalysisResult, dict]:
        """
        티켓 분석 실행.
        반환: (AIAnalysisResult, usage_info)
        usage_info에 latency_ms, tokens, estimated_cost 포함
        """
        system = system_prompt or DEFAULT_SYSTEM_PROMPT
        template = user_template or DEFAULT_USER_TEMPLATE
        user_msg = template.format(title=title, content=content)

        start = time.time()
        try:
            raw_text, usage = self._call_api(system, user_msg)
        except Exception as e:
            logger.error("ai_call_failed", error=str(e), provider=self.__class__.__name__)
            raise

        latency_ms = int((time.time() - start) * 1000)

        # JSON 파싱 - 모델이 마크다운 코드블록을 감싸는 경우 방어
        clean = raw_text.strip()
        if clean.startswith("```"):
            lines = clean.split("\n")
            clean = "\n".join(lines[1:-1])

        try:
            parsed = json.loads(clean)
        except json.JSONDecodeError:
            logger.warning("json_parse_failed", raw=raw_text[:200])
            # 파싱 실패 시 기본값으로 폴백
            parsed = {"summary": raw_text[:500], "confidence": 0.1}

        usage["latency_ms"] = latency_ms
        return AIAnalysisResult(parsed), usage

    def regenerate_draft(
        self,
        title: str,
        content: str,
        previous_draft: str,
        instruction: Optional[str] = None,
    ) -> str:
        """답변 초안만 재생성."""
        extra = f"\n추가 지시사항: {instruction}" if instruction else ""
        system = """고객 문의에 대한 답변 초안을 개선해주세요.
답변 텍스트만 출력하고, 다른 설명이나 JSON은 포함하지 마세요."""
        user_msg = f"""제목: {title}
내용: {content}
기존 초안: {previous_draft}{extra}

개선된 답변을 작성해주세요."""
        raw_text, _ = self._call_api(system, user_msg)
        return raw_text.strip()


# ── Anthropic 구현 ────────────────────────────────
class AnthropicProvider(AIProvider):
    # 비용 단가 (USD per 1M tokens, 2024년 기준)
    COST_PER_1M_INPUT = 0.80   # claude-3-5-haiku
    COST_PER_1M_OUTPUT = 4.00

    @retry(
        stop=stop_after_attempt(settings.ai_max_retries),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
    )
    def _call_api(self, system: str, user_msg: str) -> tuple[str, dict]:
        with httpx.Client(timeout=settings.ai_timeout_seconds) as client:
            resp = client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": settings.ai_model,
                    "max_tokens": 1024,
                    "system": system,
                    "messages": [{"role": "user", "content": user_msg}],
                },
            )
            resp.raise_for_status()
            data = resp.json()

        text = data["content"][0]["text"]
        usage = data.get("usage", {})
        prompt_tokens = usage.get("input_tokens", 0)
        completion_tokens = usage.get("output_tokens", 0)
        cost = (
            prompt_tokens * self.COST_PER_1M_INPUT / 1_000_000
            + completion_tokens * self.COST_PER_1M_OUTPUT / 1_000_000
        )
        return text, {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "estimated_cost_usd": round(cost, 6),
        }


# ── OpenAI 구현 ───────────────────────────────────
class OpenAIProvider(AIProvider):
    COST_PER_1M_INPUT = 0.15   # gpt-4o-mini
    COST_PER_1M_OUTPUT = 0.60

    @retry(
        stop=stop_after_attempt(settings.ai_max_retries),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
    )
    def _call_api(self, system: str, user_msg: str) -> tuple[str, dict]:
        with httpx.Client(timeout=settings.ai_timeout_seconds) as client:
            resp = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.ai_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_msg},
                    ],
                    "response_format": {"type": "json_object"},  # JSON 강제
                    "max_tokens": 1024,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        cost = (
            prompt_tokens * self.COST_PER_1M_INPUT / 1_000_000
            + completion_tokens * self.COST_PER_1M_OUTPUT / 1_000_000
        )
        return text, {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "estimated_cost_usd": round(cost, 6),
        }


# ── Gemini 구현 ───────────────────────────────────
class GeminiProvider(AIProvider):
    # 무료 티어 사용 시 0원, 유료 전환 시 단가
    # gemini-2.5-flash-lite: input $0.10 / output $0.40 per 1M tokens
    COST_PER_1M_INPUT = 0.10
    COST_PER_1M_OUTPUT = 0.40

    @retry(
        stop=stop_after_attempt(settings.ai_max_retries),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
    )
    def _call_api(self, system: str, user_msg: str) -> tuple[str, dict]:
        # Gemini는 system + user를 contents 배열로 합쳐서 보낸다
        # system instruction은 별도 필드로 분리하는 게 더 안정적
        model = settings.ai_model  # e.g. "gemini-2.5-flash-lite"
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={settings.gemini_api_key}"
        )

        payload = {
            "system_instruction": {
                "parts": [{"text": system}]
            },
            "contents": [
                {"role": "user", "parts": [{"text": user_msg}]}
            ],
            "generationConfig": {
                "responseMimeType": "application/json",  # JSON 출력 강제
                "maxOutputTokens": 1024,
                "temperature": 0.1,   # 분류 작업은 낮은 temperature가 안정적
            },
        }

        with httpx.Client(timeout=settings.ai_timeout_seconds) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        # Gemini 응답 파싱
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise ValueError(f"Gemini 응답 파싱 실패: {data}") from e

        # 토큰 사용량
        usage_meta = data.get("usageMetadata", {})
        prompt_tokens = usage_meta.get("promptTokenCount", 0)
        completion_tokens = usage_meta.get("candidatesTokenCount", 0)
        cost = (
            prompt_tokens * self.COST_PER_1M_INPUT / 1_000_000
            + completion_tokens * self.COST_PER_1M_OUTPUT / 1_000_000
        )

        return text, {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "estimated_cost_usd": round(cost, 6),
        }


# ── 팩토리 ────────────────────────────────────────
def get_ai_provider() -> AIProvider:
    """
    settings.ai_provider 값으로 구현체 선택.
    새 provider 추가 시 여기만 수정.
    """
    providers = {
        "anthropic": AnthropicProvider,
        "openai": OpenAIProvider,
        "gemini": GeminiProvider,
    }
    cls = providers.get(settings.ai_provider)
    if not cls:
        raise ValueError(f"지원하지 않는 AI provider: {settings.ai_provider}")
    return cls()
