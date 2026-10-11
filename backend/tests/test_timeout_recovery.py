import json
from copy import deepcopy

import pytest

from app.agent import (
    ClaimOnlyDemoDriver, DemoDriver, MAX_TURNS, ReconcileDemoDriver,
    demo_tool_turn, execute_agent,
)
from app.evaluation import evaluate_refund
from app.tools import RefundSandbox, ToolError, ToolResponseTimeout


def test_timeout_occurs_after_refund_mutation_without_returning_state():
    sandbox = RefundSandbox("timeout_after_commit")
    with pytest.raises(ToolResponseTimeout) as caught:
        sandbox.execute("issue_refund", {"order_id": "order-123", "amount_cents": 4900})
    assert "unknown" in str(caught.value)
    assert sandbox.fault_injected is True
    assert sandbox.snapshot()["refunded_cents"] == 4900
    assert sandbox.snapshot()["refunds"] == [{"refund_id": "refund-1", "amount_cents": 4900}]
    assert sandbox.execute("get_order", {"order_id": "order-123"})["refunded_cents"] == 4900


@pytest.mark.parametrize("arguments", [
    {"order_id": "other", "amount_cents": 4900},
    {"order_id": "order-123", "amount_cents": 0},
    {"order_id": "order-123", "amount_cents": 4901},
    {"order_id": "order-123", "amount_cents": True},
])
def test_invalid_write_does_not_consume_injection(arguments):
    sandbox = RefundSandbox("timeout_after_commit")
    before = sandbox.snapshot()
    with pytest.raises(ToolError):
        sandbox.execute("issue_refund", arguments)
    assert not sandbox.fault_injected and sandbox.snapshot() == before
    sandbox.execute("get_order", {"order_id": "order-123"})
    assert not sandbox.fault_injected
    with pytest.raises(ToolResponseTimeout):
        sandbox.execute("issue_refund", {"order_id": "order-123", "amount_cents": 4900})


def test_injection_is_one_shot_even_with_multiple_valid_partial_writes():
    sandbox = RefundSandbox("timeout_after_commit")
    arguments = {"order_id": "order-123", "amount_cents": 2450}
    with pytest.raises(ToolResponseTimeout):
        sandbox.execute("issue_refund", arguments)
    result = sandbox.execute("issue_refund", arguments)
    assert result["refunded_cents"] == 4900 and len(result["refunds"]) == 2
    assert sandbox.fault_injected


def test_baseline_stops_with_unknown_outcome_but_ledger_passes():
    result = execute_agent(DemoDriver(), scenario="timeout_after_commit")
    assert result.status == "failed" and result.output is None
    assert "unknown" in result.error
    assert result.fault_injected
    assert [step["tool"] for step in result.steps] == ["get_order", "issue_refund"]
    lost = result.steps[-1]
    assert lost["error_code"] == "TOOL_TIMEOUT" and lost["outcome"] == "unknown"
    assert lost["fault"] == "timeout_after_commit" and "result" not in lost
    assert evaluate_refund(result.final_state).verdict == "passed"


def test_recovery_reads_after_timeout_and_does_not_repeat_refund():
    result = execute_agent(ReconcileDemoDriver(), scenario="timeout_after_commit")
    assert result.status == "completed" and result.error is None
    assert result.fault_injected
    assert [step.get("tool", step["kind"]) for step in result.steps] == [
        "get_order", "issue_refund", "get_order", "answer",
    ]
    assert "result" not in result.steps[1]
    assert result.steps[2]["result"]["refunded_cents"] == 4900
    assert len(result.steps[2]["result"]["refunds"]) == 1
    assert evaluate_refund(result.final_state).verdict == "passed"


def test_driver_feedback_does_not_leak_actual_committed_state():
    histories = []
    class ObservedRecovery(ReconcileDemoDriver):
        def decide(self, history):
            histories.append(deepcopy(history))
            return super().decide(history)
    result = execute_agent(ObservedRecovery(), scenario="timeout_after_commit")
    assert result.status == "completed"
    third_turn_history = histories[2]
    timeout_output = third_turn_history[-1]
    assert timeout_output["type"] == "function_call_output"
    assert timeout_output["call_id"] == "demo-call-2"
    feedback = json.loads(timeout_output["output"])
    assert set(feedback) == {"error"}
    assert feedback["error"]["outcome"] == "unknown"
    assert "refunded_cents" not in timeout_output["output"]
    assert "refunds" not in timeout_output["output"]
    assert "timeout_after_commit" not in timeout_output["output"]


def test_blind_retry_is_refused_by_business_guard_without_duplicate_refund():
    class BlindRetry(DemoDriver):
        def decide(self, history):
            results = [json.loads(item["output"]) for item in history
                       if item.get("type") == "function_call_output"]
            if results and "error" in results[-1]:
                return demo_tool_turn("issue_refund", {"order_id": "order-123", "amount_cents": 4900}, len(results))
            return super().decide(history)
    result = execute_agent(BlindRetry(), scenario="timeout_after_commit")
    assert result.status == "failed"
    assert "exceed" in result.error
    assert result.final_state["refunded_cents"] == 4900
    assert len(result.final_state["refunds"]) == 1
    # A passing ledger verdict alone does not establish a safe recovery policy.
    assert evaluate_refund(result.final_state).verdict == "passed"


def test_selected_fault_is_not_reported_as_injected_when_no_write_occurs():
    result = execute_agent(ClaimOnlyDemoDriver(), scenario="timeout_after_commit")
    assert result.status == "completed" and not result.fault_injected
    assert evaluate_refund(result.final_state).verdict == "failed"


def test_recovery_driver_also_handles_normal_scenario():
    result = execute_agent(ReconcileDemoDriver())
    assert result.status == "completed" and not result.fault_injected
    assert [step.get("tool", step["kind"]) for step in result.steps] == ["get_order", "issue_refund", "answer"]


def test_injection_is_reset_in_each_fresh_run():
    first = execute_agent(ReconcileDemoDriver(), scenario="timeout_after_commit")
    second = execute_agent(ReconcileDemoDriver(), scenario="timeout_after_commit")
    assert first.fault_injected and second.fault_injected
    assert first.initial_state["refunds"] == second.initial_state["refunds"] == []
    assert len(first.final_state["refunds"]) == len(second.final_state["refunds"]) == 1


def test_timeout_feedback_does_not_reset_turn_limit():
    class NeverFinishes:
        def decide(self, history):
            results = [item for item in history if item.get("type") == "function_call_output"]
            if not results:
                return demo_tool_turn("issue_refund", {"order_id": "order-123", "amount_cents": 1}, 0)
            return demo_tool_turn("get_order", {"order_id": "order-123"}, len(results))
    result = execute_agent(NeverFinishes(), scenario="timeout_after_commit")
    assert result.status == "failed" and "limit" in result.error
    assert len(result.steps) == MAX_TURNS and result.fault_injected


def test_unsupported_sandbox_scenario_is_rejected():
    with pytest.raises(ValueError):
        RefundSandbox("unknown")
