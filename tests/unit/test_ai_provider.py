"""
AI 프로바이더 유닛 테스트.
실제 API를 호출하지 않고 mock으로 테스트한다.
"""
import json
import pytest
from unittest.mock import patch, MagicMock

from app.services.ai_provider import (
    AnthropicProvider,
    GeminiProvider,
    AIAnalysisResult,
    normalize_analysis_payload,
)

MOCK_VALID_RESPONSE = json.dumps({
    "category": "billing",
    "urgency": "high",
    "sentiment": "negative",
    "summary": "사용자가 중복 결제를 주장하며 환불을 요청함",
    "suggested_team": "payments",
    "draft_reply": "안녕하세요. 결제 내역을 즉시 확인하겠습니다.",
    "confidence": 0.92,
})


class TestAIAnalysisResult:
    def test_parse_valid_json(self):
        raw = {
            "category": "billing",
            "urgency": "high",
            "sentiment": "negative",
            "summary": "테스트 요약",
            "suggested_team": "payments",
            "draft_reply": "답변 초안",
            "confidence": 0.9,
        }
        result = AIAnalysisResult(raw)
        assert result.category == "billing"
        assert result.urgency == "high"
        assert result.confidence == 0.9

    def test_parse_missing_fields_uses_defaults(self):
        result = AIAnalysisResult({})
        assert result.category == "other"
        assert result.urgency == "medium"
        assert result.confidence == 0.5

    def test_invalid_choices_are_normalized_to_defaults(self):
        result = AIAnalysisResult({
            "category": "invoice",
            "urgency": "urgent",
            "sentiment": "angry",
            "suggested_team": "billing-team",
        })
        assert result.category == "other"
        assert result.urgency == "medium"
        assert result.sentiment == "neutral"
        assert result.suggested_team == "support"

    def test_confidence_is_clamped_and_non_numeric_falls_back(self):
        high = AIAnalysisResult({"confidence": 1.7})
        low = AIAnalysisResult({"confidence": -3})
        invalid = AIAnalysisResult({"confidence": "not-a-number"})
        assert high.confidence == 1.0
        assert low.confidence == 0.0
        assert invalid.confidence == 0.5

    def test_text_fields_are_coerced_to_strings(self):
        result = AIAnalysisResult({"summary": None, "draft_reply": 12345})
        assert result.summary == ""
        assert result.draft_reply == "12345"

    def test_to_dict(self):
        result = AIAnalysisResult({"category": "bug", "confidence": 0.7})
        d = result.to_dict()
        assert "category" in d
        assert "confidence" in d


class TestNormalizeAnalysisPayload:
    def test_payload_normalization_returns_expected_defaults(self):
        normalized = normalize_analysis_payload(None)
        assert normalized == {
            "category": "other",
            "urgency": "medium",
            "sentiment": "neutral",
            "summary": "",
            "suggested_team": "support",
            "draft_reply": "",
            "confidence": 0.5,
        }


class TestAnthropicProvider:
    def _make_mock_response(self, text: str):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "content": [{"text": text}],
            "usage": {"input_tokens": 100, "output_tokens": 200},
        }
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    def test_analyze_ticket_success(self):
        provider = AnthropicProvider()
        mock_resp = self._make_mock_response(MOCK_VALID_RESPONSE)

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.post.return_value = mock_resp

            result, usage = provider.analyze_ticket(
                title="결제가 두 번 됐어요",
                content="어제 결제했는데 오늘 또 청구됐습니다.",
            )

        assert result.category == "billing"
        assert result.urgency == "high"
        assert result.confidence == 0.92
        assert usage["prompt_tokens"] == 100
        assert usage["completion_tokens"] == 200
        assert "latency_ms" in usage

    def test_analyze_ticket_handles_markdown_wrapped_json(self):
        """모델이 ```json ... ``` 으로 감쌀 경우 방어 처리."""
        wrapped = f"```json\n{MOCK_VALID_RESPONSE}\n```"
        provider = AnthropicProvider()
        mock_resp = self._make_mock_response(wrapped)

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.post.return_value = mock_resp

            result, _ = provider.analyze_ticket("제목", "내용")

        assert result.category == "billing"

    def test_analyze_ticket_handles_invalid_json(self):
        """JSON 파싱 실패 시 기본값으로 폴백."""
        provider = AnthropicProvider()
        mock_resp = self._make_mock_response("이것은 JSON이 아닙니다")

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.post.return_value = mock_resp

            result, _ = provider.analyze_ticket("제목", "내용")

        assert result.confidence == 0.1  # 파싱 실패 폴백값


class TestGeminiProvider:
    def _make_mock_response(self, text: str):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": text}]}}],
            "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 180},
        }
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    def test_analyze_ticket_success(self):
        provider = GeminiProvider()
        mock_resp = self._make_mock_response(MOCK_VALID_RESPONSE)

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.post.return_value = mock_resp

            result, usage = provider.analyze_ticket(
                title="결제가 두 번 됐어요",
                content="어제 결제했는데 오늘 또 청구됐습니다.",
            )

        assert result.category == "billing"
        assert result.urgency == "high"
        assert usage["prompt_tokens"] == 120
        assert usage["completion_tokens"] == 180

    def test_gemini_response_parse_failure(self):
        """candidates 구조가 비어있을 때 ValueError."""
        provider = GeminiProvider()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"candidates": []}  # 빈 응답
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.post.return_value = mock_resp

            with pytest.raises(ValueError, match="Gemini 응답 파싱 실패"):
                provider.analyze_ticket("제목", "내용")
