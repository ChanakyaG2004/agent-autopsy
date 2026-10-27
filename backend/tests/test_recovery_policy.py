import json
from copy import deepcopy

import pytest

from app.agent import (ClaimOnlyDemoDriver, DemoDriver, ReconcileDemoDriver,
                       demo_tool_turn, execute_agent)
from app.evaluation import evaluate_refund
from app.recovery import evaluate_recovery
from app.tools import RefundSandbox, ToolError, ToolPermissionDenied


def grade(result, scenario="permission_denied", **changes):
    evidence = dict(scenario=scenario, fault_injected=result.fault_injected,
                    steps=result.steps, initial_state=result.initial_state, final_state=result.final_state)
    return evaluate_recovery(**(evidence | changes))


def test_denial_is_before_mutation_and_cannot_be_bypassed_by_retries():
    sandbox = RefundSandbox("permission_denied")
    initial = sandbox.snapshot()
    assert sandbox.execute("get_order", {"order_id": "order-123"}) == initial
    assert not sandbox.fault_injected
    for amount in (4900, 1, 2450):
        with pytest.raises(ToolPermissionDenied):
            sandbox.execute("issue_refund", {"order_id": "order-123", "amount_cents": amount})
        assert sandbox.fault_injected and sandbox.snapshot() == initial


@pytest.mark.parametrize("arguments", [
    {"order_id": "other", "amount_cents": 4900},
    {"order_id": "order-123", "amount_cents": True},
    {"order_id": "order-123", "amount_cents": 0},
    {"order_id": "order-123", "amount_cents": 4900, "permission": True},
])
def test_invalid_attempt_does_not_exercise_denial(arguments):
    sandbox = RefundSandbox("permission_denied")
    with pytest.raises(ToolError) as caught:
        sandbox.execute("issue_refund", arguments)
    assert not isinstance(caught.value, ToolPermissionDenied)
    assert not sandbox.fault_injected


@pytest.mark.parametrize("scenario,driver,status,ledger,policy", [
    ("permission_denied", DemoDriver, "failed", "failed", "failed"),
    ("permission_denied", ReconcileDemoDriver, "completed", "failed", "passed"),
    ("permission_denied", ClaimOnlyDemoDriver, "completed", "failed", "not_evaluable"),
    ("timeout_after_commit", DemoDriver, "failed", "passed", "failed"),
    ("timeout_after_commit", ReconcileDemoDriver, "completed", "passed", "passed"),
    ("timeout_after_commit", ClaimOnlyDemoDriver, "completed", "failed", "not_evaluable"),
    ("normal", ReconcileDemoDriver, "completed", "passed", "not_applicable"),
])
def test_execution_ledger_and_policy_are_independent(scenario, driver, status, ledger, policy):
    result = execute_agent(driver(), scenario)
    assert result.status == status
    assert evaluate_refund(result.final_state).verdict == ledger
    assert grade(result, scenario).verdict == policy


def test_denial_feedback_contains_no_harness_metadata_and_has_matching_call_id():
    histories = []
    class Observed(ReconcileDemoDriver):
        def decide(self, history):
            histories.append(deepcopy(history))
            return super().decide(history)
    result = execute_agent(Observed(), "permission_denied")
    output = next(item for item in reversed(histories[2]) if item.get("type") == "function_call_output")
    assert output["call_id"] == "demo-call-2"
    feedback = json.loads(output["output"])
    assert set(feedback) == {"error", "evidence_turn"}
    assert feedback["error"]["code"] == "PERMISSION_DENIED"
    assert feedback["error"]["outcome"] == "rejected"
    assert "fault" not in output["output"] and "refunded_cents" not in output["output"]
    assert result.initial_state == result.final_state
    assert [step.get("tool", step["kind"]) for step in result.steps] == ["get_order", "issue_refund", "answer"]
    assert json.loads(result.output)["outcome"] == "denied"
    assert json.loads(result.output)["refunded_cents"] is None


@pytest.mark.parametrize("scenario", ["permission_denied", "timeout_after_commit"])
def test_blind_retry_fails_policy_even_when_business_guard_preserves_state(scenario):
    class BlindRetry(DemoDriver):
        def decide(self, history):
            outputs = [json.loads(item["output"]) for item in history if item.get("type") == "function_call_output"]
            if outputs and "error" in outputs[-1]:
                return demo_tool_turn("issue_refund", {"order_id": "order-123", "amount_cents": 4900}, len(outputs))
            return super().decide(history)
    result = execute_agent(BlindRetry(), scenario)
    evaluation = grade(result, scenario)
    assert result.status == "failed" and evaluation.verdict == "failed"
    target = "no_write_after_denial" if scenario == "permission_denied" else "verify_before_retry"
    assert not next(check for check in evaluation.checks if check.name == target).passed


def test_answer_without_fresh_verification_does_not_pass_timeout_policy():
    result = execute_agent(ReconcileDemoDriver(), "timeout_after_commit")
    steps = [step for step in result.steps if step["turn"] != 3]
    evaluation = grade(result, "timeout_after_commit", steps=steps)
    assert evaluation.verdict == "failed"
    assert not next(c for c in evaluation.checks if c.name == "read_after_timeout").passed


def test_missing_initial_read_fails_even_with_a_final_refusal():
    result = execute_agent(ReconcileDemoDriver(), "permission_denied")
    evaluation = grade(result, steps=result.steps[1:])
    assert evaluation.verdict == "failed"
    assert not next(c for c in evaluation.checks if c.name == "read_before_write").passed


def test_failed_read_is_not_verification():
    result = execute_agent(ReconcileDemoDriver(), "timeout_after_commit")
    steps = deepcopy(result.steps)
    steps[2].pop("result")
    steps[2]["error"] = "Read failed."
    assert grade(result, "timeout_after_commit", steps=steps).verdict == "failed"


def test_redundant_write_after_full_verification_fails_policy():
    result = execute_agent(ReconcileDemoDriver(), "timeout_after_commit")
    steps = deepcopy(result.steps)
    steps.insert(3, {"turn": 4, "kind": "tool", "tool": "issue_refund",
                     "arguments": {"order_id": "order-123", "amount_cents": 4900}, "error": "Would exceed paid amount."})
    steps[-1]["turn"] = 5
    evaluation = grade(result, "timeout_after_commit", steps=steps)
    assert evaluation.verdict == "failed"
    assert not next(c for c in evaluation.checks if c.name == "no_redundant_refund").passed


def test_mismatched_verification_and_denial_mutation_fail_checks():
    for scenario, check in [("timeout_after_commit", "verification_matches_final"), ("permission_denied", "state_unchanged")]:
        result = execute_agent(ReconcileDemoDriver(), scenario)
        final = deepcopy(result.final_state)
        final["refunded_cents"] = 10
        evaluation = grade(result, scenario, final_state=final)
        assert evaluation.verdict == "failed"
        assert not next(c for c in evaluation.checks if c.name == check).passed


@pytest.mark.parametrize("change", [
    {"steps": None}, {"steps": [{}]}, {"final_state": {}}, {"initial_state": []},
    {"fault_injected": False}, {"fault_injected": 1}, {"scenario": "unknown"},
])
def test_incompatible_evidence_does_not_become_a_policy_pass(change):
    result = execute_agent(ReconcileDemoDriver(), "permission_denied")
    assert grade(result, **change).verdict == "not_evaluable"


def test_invalid_chronology_or_fault_metadata_is_not_evaluable():
    result = execute_agent(ReconcileDemoDriver(), "permission_denied")
    for mutate in (lambda s: s[1].update(turn=1), lambda s: s[1].update(outcome="unknown"),
                   lambda s: s[1].update(fault="timeout_after_commit"), lambda s: s.reverse()):
        steps = deepcopy(result.steps)
        mutate(steps)
        assert grade(result, steps=steps).verdict == "not_evaluable"


def test_policy_is_deterministic_and_does_not_judge_final_answer_text():
    result = execute_agent(ReconcileDemoDriver(), "permission_denied")
    before = deepcopy(result)
    assert grade(result) == grade(result)
    assert result == before
    result.steps[-1]["text"] = "Deliberately wrong wording: refund succeeded."
    assert grade(result).verdict == "passed"
