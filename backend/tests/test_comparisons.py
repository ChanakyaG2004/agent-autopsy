from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.comparisons import ComparisonSide, compare_sides
from app.evaluation import evaluate_refund, unavailable_evaluation
from app.model_telemetry import ModelRequestConfiguration, ModelRequestMeasurement, TokenUsage, summarize_requests
from app.recovery import RecoveryEvaluation
from app.schemas import RunRead
from app.tools import RefundSandbox


def measured(*, tokens=10, missing=False, model="local-model", digest="weights-a", prompt="prompt-a", provider="ollama"):
    configuration = ModelRequestConfiguration(
        instructions_sha256=prompt, tool_schemas_sha256="tools", max_output_tokens=1024,
        max_turns=6, timeout_seconds=60.0, max_retries=0, store=None,
        parallel_tool_calls=None, model_digest=digest if provider == "ollama" else None,
    )
    requests = [ModelRequestMeasurement(
        sequence=1, requested_model=model, reported_model=model, duration_ms=100.0,
        outcome="response", response_status="completed", error_type=None, usage_status="reported",
        usage=TokenUsage(input_tokens=tokens, output_tokens=0, total_tokens=tokens),
    )]
    if missing:
        requests.append(ModelRequestMeasurement(
            sequence=2, requested_model=model, reported_model=None, duration_ms=50.0,
            outcome="error", response_status=None, error_type="timeout", usage_status="unavailable", usage=None,
        ))
    return summarize_requests(model, requests, configuration, provider=provider)


def side(**changes):
    state = RefundSandbox().snapshot()
    values = dict(id=uuid4(), experiment_id=uuid4(), status="completed", mode="ollama", scenario="normal",
                  fault_injected=False, model_name="local-model", trace_id=None, evaluation=evaluate_refund(state),
                  recovery_evaluation=RecoveryEvaluation(verdict="not_applicable", checks=[]),
                  model_telemetry=measured(), task="Refund order-123", output="A claim", error=None,
                  steps=[], initial_state=state, final_state=state, started_at=datetime.now(timezone.utc),
                  finished_at=datetime.now(timezone.utc))
    values.update(changes)
    return ComparisonSide(experiment_name="Observation", agent_version="refund-v1", run=RunRead(**values))


def metrics(report):
    return {row.field: row for row in report.measurements}


def test_comparison_preserves_grades_and_records_signed_delta_and_prompt_change():
    baseline = side()
    sandbox = RefundSandbox()
    sandbox.execute("issue_refund", {"order_id": "order-123", "amount_cents": 4900})
    candidate = side(evaluation=evaluate_refund(sandbox.snapshot()), final_state=sandbox.snapshot(),
                     model_telemetry=measured(tokens=0, prompt="prompt-b"))
    report = compare_sides(baseline, candidate)
    assert report.outcomes_comparable and report.tokens_comparable and report.request_measurements_comparable
    assert not report.recovery_comparable
    assert report.baseline.run.evaluation.verdict == "failed"
    assert report.candidate.run.evaluation.verdict == "passed"
    assert metrics(report)["total_tokens"].delta == -10
    assert metrics(report)["request_time"].delta == 0
    assert metrics(report)["total_tokens"].candidate == 0
    assert [(c.field, c.baseline, c.candidate) for c in report.configuration_changes] == [
        ("request.instructions_sha256", "prompt-a", "prompt-b")]


@pytest.mark.parametrize("changes,check", [
    ({"scenario": "permission_denied"}, "same_scenario"),
    ({"task": "Another task"}, "same_task"),
    ({"initial_state": {}}, "same_initial_state"),
    ({"status": "running", "finished_at": None}, "terminal_evidence"),
    ({"status": "interrupted"}, "terminal_evidence"),
])
def test_mismatched_cases_suppress_every_delta_but_preserve_raw_evidence(changes, check):
    report = compare_sides(side(), side(**changes))
    assert not report.outcomes_comparable and not report.tokens_comparable
    assert not report.request_measurements_comparable
    assert not next(c for c in report.checks if c.name == check).passed
    assert all(row.delta is None for row in report.measurements)
    assert metrics(report)["total_tokens"].baseline == 10


def test_changed_task_contract_suppresses_deltas():
    candidate = side().model_copy(update={"agent_version": "refund-v2"})
    assert not compare_sides(side(), candidate).outcomes_comparable


def test_different_security_evaluator_versions_are_not_compared_as_equal_evidence():
    from app.assurance import SecurityEvaluation
    from app.evaluation import EvaluationCheck
    check = EvaluationCheck(name="registered_tools", passed=True, reason="Allowed tools")
    first = side(security_evaluation=SecurityEvaluation(evaluator_version="tool-policy-v1", verdict="passed", attempted_tools=1, checks=[check]))
    second = side(security_evaluation=SecurityEvaluation(verdict="passed", attempted_tools=1, checks=[check]))
    report = compare_sides(first, second)
    assert report.outcomes_comparable and not report.security_comparable
    assert report.baseline.run.security_evaluation.evaluator_version == "tool-policy-v1"
    assert report.candidate.run.security_evaluation.evaluator_version == "tool-policy-v2"


@pytest.mark.parametrize("evaluation", [None, unavailable_evaluation()])
def test_missing_grade_is_not_a_task_failure_or_comparable(evaluation):
    report = compare_sides(side(), side(evaluation=evaluation))
    assert not report.outcomes_comparable
    assert report.tokens_comparable
    assert report.candidate.run.evaluation == evaluation


def test_changed_ledger_expectation_is_not_comparable():
    evaluation = evaluate_refund(RefundSandbox().snapshot())
    evaluation.expected = evaluation.expected.model_copy(update={"refund_count": 2})
    assert not compare_sides(side(), side(evaluation=evaluation)).outcomes_comparable


@pytest.mark.parametrize("telemetry", [None, measured(missing=True), measured(model="other"),
                                          measured(digest="other"), measured(digest=None),
                                          measured(model=""), measured(provider="openai")])
def test_unavailable_partial_or_different_model_usage_never_gets_a_token_delta(telemetry):
    report = compare_sides(side(), side(model_telemetry=telemetry))
    assert report.outcomes_comparable and not report.tokens_comparable
    assert all(metrics(report)[key].delta is None for key in ("input_tokens", "output_tokens", "total_tokens"))
    if telemetry:
        assert report.request_measurements_comparable
        assert metrics(report)["total_tokens"].candidate == telemetry.known_usage.total_tokens
    else:
        assert not report.request_measurements_comparable
        assert metrics(report)["total_tokens"].candidate is None


def test_recovery_requires_actual_fault_exercise_and_grade_on_both_sides():
    passed = RecoveryEvaluation(verdict="passed", checks=[])
    failed = RecoveryEvaluation(verdict="failed", checks=[])
    left = side(scenario="timeout_after_commit", fault_injected=True, recovery_evaluation=failed, status="failed")
    right = side(scenario="timeout_after_commit", fault_injected=True, recovery_evaluation=passed)
    report = compare_sides(left, right)
    assert report.recovery_comparable and report.outcomes_comparable
    assert report.baseline.run.status == "failed" and report.candidate.run.status == "completed"
    assert not compare_sides(left, side(scenario="timeout_after_commit", recovery_evaluation=passed)).recovery_comparable
    assert not compare_sides(left, side(scenario="timeout_after_commit", fault_injected=True,
                                       recovery_evaluation=RecoveryEvaluation(verdict="not_evaluable", checks=[]))).recovery_comparable


def test_global_run_listing_and_comparison_are_read_only_and_paginated(client, monkeypatch):
    def run(mode):
        experiment = client.post("/experiments", json={"name": "Saved evidence", "agent_version": "refund-v1", "scenarios": ["normal"]}).json()
        return client.post(f'/experiments/{experiment["id"]}/runs', json={"mode": mode}).json()
    first, second = run("demo_claim_only"), run("demo")
    monkeypatch.setattr("app.execution.make_driver", lambda *_: pytest.fail("Reading must not execute an agent"))
    monkeypatch.setattr("app.execution.evaluate_refund", lambda *_: pytest.fail("Reading must not regrade evidence"))
    listed = client.get("/runs").json()
    expected = sorted([first, second], key=lambda row: (row["started_at"], row["id"]), reverse=True)
    assert [row["id"] for row in listed] == [row["id"] for row in expected]
    assert listed[0]["experiment_name"] == "Saved evidence" and listed[0]["instructions_sha256"] is None
    assert client.get("/runs?limit=1&offset=1").json() == listed[1:]
    response = client.get("/run-comparisons", params={"baseline_id": first["id"], "candidate_id": second["id"]})
    assert response.status_code == 200
    report = response.json()
    assert report["baseline"]["run"] == first and report["candidate"]["run"] == second
    assert report["outcomes_comparable"] and not report["tokens_comparable"]
    assert client.get("/runs").json() == listed
    for query in ("limit=0", "limit=101", "offset=-1"):
        assert client.get(f"/runs?{query}").status_code == 422
    assert client.get("/run-comparisons", params={"baseline_id": first["id"], "candidate_id": first["id"]}).status_code == 422
    assert client.get("/run-comparisons", params={"baseline_id": first["id"], "candidate_id": str(uuid4())}).status_code == 404
    assert client.get("/run-comparisons", params={"baseline_id": "bad", "candidate_id": second["id"]}).status_code == 422
