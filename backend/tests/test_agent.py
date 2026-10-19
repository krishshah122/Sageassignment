from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.agent.llm import GROQ_CHAT_COMPLETIONS_URL, LLMError, build_messages, request_decision
from app.agent.tools import AgentDecision, execute_mock_tool


def test_mock_tools_validate_inputs_and_report_simulated_results() -> None:
    result = execute_mock_tool(
        "create_internal_note",
        {"note": "Reviewed the shipment delay."},
    )
    assert result == {
        "tool": "create_internal_note",
        "arguments": {"note": "Reviewed the shipment delay."},
        "result": {"note": "Reviewed the shipment delay.", "created": "simulated"},
    }

    with pytest.raises(ValueError):
        execute_mock_tool("create_internal_note", {"note": "   "})
    with pytest.raises(ValueError, match="Unsupported tool"):
        execute_mock_tool("unexpected_tool", {})
    assert execute_mock_tool(
        "mark_order_for_review",
        {"reason": "Payment status needs operator confirmation."},
    )["result"]["review"] == "simulated"


def test_agent_messages_include_order_memory_events_and_only_enabled_tools() -> None:
    messages = build_messages(
        base_instruction="Watch order status.",
        order_id="ORD-3",
        order_context={"status": "delayed"},
        extra_instructions=["Escalate delays."],
        memory_summary="Payment confirmed.",
        recent_timeline=[],
        events=[{"type": "shipment_delayed", "payload": {"reason": "weather"}}],
        cause="important_event",
        finalizing=False,
        available_tools=["create_internal_note", "mark_order_for_review", "not-a-tool"],
    )
    assert '"order_id": "ORD-3"' in messages[1]["content"]
    assert '"shipment_delayed"' in messages[1]["content"]
    assert "create_internal_note" in messages[0]["content"]
    assert "mark_order_for_review" in messages[0]["content"]
    assert "not-a-tool" not in messages[0]["content"]
    assert "schedule_next_wakeup" not in messages[0]["content"]
    assert "When not finalizing, final_output MUST be null." in messages[0]["content"]
    assert "learnings (non-empty string)" in messages[0]["content"]
    assert "important_actions (array of objects, or an empty array)" in messages[0]["content"]
    assert "summary and memory_summary must be non-empty strings" in messages[0]["content"]


@pytest.mark.asyncio
async def test_groq_request_sends_json_mode_and_validates_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"summary":"Checked order.","memory_summary":"No issues.",'
                                '"actions":[],"next_wakeup_seconds":45,"final_output":null}'
                            )
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured["timeout"] = kwargs["timeout"]

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any]):
            captured.update({"url": url, "headers": headers, "json": json})
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    decision = await request_decision(
        messages=[{"role": "user", "content": "{}"}],
        api_key="test-secret",
        model="test-model",
    )

    assert isinstance(decision, AgentDecision)
    assert decision.next_wakeup_seconds == 45
    assert captured["url"] == GROQ_CHAT_COMPLETIONS_URL
    assert captured["headers"]["Authorization"] == "Bearer test-secret"
    assert captured["json"]["model"] == "test-model"
    assert captured["json"]["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "agent_decision",
            "strict": False,
            "schema": AgentDecision.model_json_schema(),
        },
    }


@pytest.mark.asyncio
async def test_groq_request_requires_key_and_rejects_invalid_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(LLMError, match="GROQ_API_KEY is required"):
        await request_decision(messages=[], api_key="", model="test-model")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"content": "not json"}}]}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, *args: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    with pytest.raises(LLMError, match="valid agent decision"):
        await request_decision(
            messages=[],
            api_key="test-secret",
            model="test-model",
        )
