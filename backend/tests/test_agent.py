import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from openai import APITimeoutError

from app.agent import AgentError, DemoDriver, MAX_TURNS, ModelTurn, ToolCall, execute_agent
from app.providers import OpenAIDriver, ProviderNotConfigured, make_driver
from app.tools import RefundSandbox, ToolError


def test_demo_runs_real_tools_and_preserves_initial_snapshot():
    result = execute_agent(DemoDriver())
    assert result.status == "completed"
    assert [step.get("tool", step["kind"]) for step in result.steps] == ["get_order", "issue_refund", "answer"]
    assert result.initial_state["refunded_cents"] == 0
    assert result.final_state["refunded_cents"] == 4900
    assert result.final_state["refunds"] == [{"refund_id": "refund-1", "amount_cents": 4900}]
    assert execute_agent(DemoDriver()).initial_state["refunds"] == []


@pytest.mark.parametrize("tool,args", [
    ("shell", {}),
    ("get_order", {"order_id": "other-order"}),
    ("issue_refund", {"order_id": "order-123", "amount_cents": "4900"}),
    ("issue_refund", {"order_id": "order-123", "amount_cents": True}),
    ("issue_refund", {"order_id": "order-123", "amount_cents": 0}),
    ("issue_refund", {"order_id": "order-123", "amount_cents": 4901}),
    ("get_order", {"order_id": "order-123", "extra": 1}),
])
def test_invalid_tools_cannot_mutate_state(tool, args):
    sandbox = RefundSandbox()
    before = sandbox.snapshot()
    with pytest.raises(ToolError):
        sandbox.execute(tool, args)
    assert sandbox.snapshot() == before


def test_duplicate_full_refund_is_rejected():
    sandbox = RefundSandbox()
    args = {"order_id": "order-123", "amount_cents": 4900}
    sandbox.execute("issue_refund", args)
    with pytest.raises(ToolError):
        sandbox.execute("issue_refund", args)
    assert len(sandbox.snapshot()["refunds"]) == 1


def test_step_limit_stops_a_looping_driver():
    driver = Mock()
    driver.decide.return_value = ModelTurn([], [ToolCall("get_order", {"order_id": "order-123"}, "call")])
    result = execute_agent(driver)
    assert result.status == "failed"
    assert driver.decide.call_count == MAX_TURNS
    assert len(result.steps) == MAX_TURNS
    assert "limit" in result.error


def test_failure_keeps_state_after_successful_mutation():
    demo = DemoDriver()
    driver = Mock()
    def decide(history):
        if len([item for item in history if item.get("type") == "function_call_output"]) == 2:
            raise AgentError("Provider unavailable.")
        return demo.decide(history)
    driver.decide.side_effect = decide
    result = execute_agent(driver)
    assert result.status == "failed" and result.output is None
    assert result.final_state["refunded_cents"] == 4900
    assert len(result.steps) == 2


def test_multiple_calls_are_refused_before_any_tool_runs():
    driver = Mock()
    driver.decide.return_value = ModelTurn([], [ToolCall("get_order", {}, "1"), ToolCall("get_order", {}, "2")])
    result = execute_agent(driver)
    assert result.status == "failed" and result.steps == []


def test_completed_is_not_a_correctness_evaluation():
    driver = Mock()
    driver.decide.return_value = ModelTurn([], answer="I refunded everything.")
    result = execute_agent(driver)
    assert result.status == "completed"
    assert result.final_state["refunded_cents"] == 0


def test_unexpected_exception_is_safe_and_terminal():
    driver = Mock()
    driver.decide.side_effect = RuntimeError("secret provider payload")
    result = execute_agent(driver)
    assert result.status == "failed"
    assert "secret" not in result.error


def test_missing_provider_config(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with pytest.raises(ProviderNotConfigured):
        make_driver("openai")


def provider_response(items, text="", status="completed"):
    return SimpleNamespace(status=status, output=[SimpleNamespace(model_dump=lambda item=item, **kw: item) for item in items], output_text=text)


def test_openai_adapter_replays_output_items_without_persisting_reasoning(monkeypatch):
    sdk = Mock()
    monkeypatch.setattr("app.providers.OpenAI", sdk)
    reasoning = {"type": "reasoning", "id": "reasoning-1", "encrypted_content": "opaque"}
    call = {"type": "function_call", "name": "get_order", "call_id": "call-1",
            "arguments": json.dumps({"order_id": "order-123"})}
    sdk.return_value.responses.create.side_effect = [
        provider_response([reasoning, call]), provider_response([], "Order read."),
    ]
    driver = OpenAIDriver("test-key", "configured-model")
    result = execute_agent(driver)
    sdk.assert_called_once_with(api_key="test-key", timeout=10.0, max_retries=0)
    history = sdk.return_value.responses.create.call_args.kwargs["input"]
    assert reasoning in history
    assert any(item.get("type") == "function_call_output" for item in history)
    assert "opaque" not in json.dumps(result.steps)
    assert sdk.return_value.responses.create.call_args.kwargs["store"] is False


@pytest.mark.parametrize("arguments", ["not json", "[]", "null"])
def test_openai_malformed_calls_fail_safely(monkeypatch, arguments):
    sdk = Mock()
    monkeypatch.setattr("app.providers.OpenAI", sdk)
    sdk.return_value.responses.create.return_value = provider_response([
        {"type": "function_call", "name": "get_order", "call_id": "1", "arguments": arguments}
    ])
    result = execute_agent(OpenAIDriver("test", "model"))
    assert result.status == "failed" and result.steps == []


def test_incomplete_model_response_does_not_execute_tools(monkeypatch):
    sdk = Mock()
    monkeypatch.setattr("app.providers.OpenAI", sdk)
    sdk.return_value.responses.create.return_value = provider_response([], status="incomplete")
    assert execute_agent(OpenAIDriver("test", "model")).status == "failed"


def test_provider_timeout_fails_without_retry_or_secret_leak(monkeypatch):
    sdk = Mock()
    monkeypatch.setattr("app.providers.OpenAI", sdk)
    sdk.return_value.responses.create.side_effect = APITimeoutError(request=Mock())
    result = execute_agent(OpenAIDriver("test-key", "model"))
    assert result.status == "failed"
    assert "timed out" in result.error
    assert "test-key" not in result.error
    sdk.return_value.responses.create.assert_called_once()


def test_rejected_tool_call_is_recorded_with_safe_error():
    driver = Mock()
    driver.decide.return_value = ModelTurn([], [ToolCall("shell", {"command": "anything"}, "1")])
    result = execute_agent(driver)
    assert result.status == "failed"
    assert "error" in result.steps[0]
    assert result.final_state == result.initial_state
