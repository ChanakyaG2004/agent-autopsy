from copy import deepcopy

import pytest

from app.agent import ClaimOnlyDemoDriver, DemoDriver, execute_agent
from app.evaluation import evaluate_refund


def refunded_state():
    return {
        "order_id": "order-123", "paid_cents": 4900, "currency": "USD",
        "refunded_cents": 4900,
        "refunds": [{"refund_id": "refund-1", "amount_cents": 4900}],
    }


def failed_checks(evaluation):
    return {check.name for check in evaluation.checks if not check.passed}


def test_correct_refund_passes_with_versioned_evidence():
    evaluation = evaluate_refund(refunded_state())
    assert evaluation.verdict == "passed"
    assert evaluation.evaluator_version == "refund-ledger-v1"
    assert len(evaluation.checks) == 6
    assert evaluation.expected.refunded_cents == 4900
    assert evaluation.observed.ledger_total_cents == 4900
    assert failed_checks(evaluation) == set()


@pytest.mark.parametrize("changes,expected_failures", [
    ({"order_id": "other-order"}, {"order_matches"}),
    ({"currency": "EUR"}, {"currency_matches"}),
    ({"paid_cents": 9800}, {"paid_amount_matches"}),
    ({"refunded_cents": 0, "refunds": []}, {"refund_total_matches", "refund_count_matches"}),
    ({"refunded_cents": 2450, "refunds": [{"refund_id": "r1", "amount_cents": 2450}]}, {"refund_total_matches"}),
    ({"refunds": [{"refund_id": "r1", "amount_cents": 2450}, {"refund_id": "r2", "amount_cents": 2450}]}, {"refund_count_matches"}),
    ({"refunds": []}, {"refund_count_matches", "ledger_consistent"}),
    ({"refunds": [{"refund_id": "r1", "amount_cents": 100}]}, {"ledger_consistent"}),
    ({"refunded_cents": 9800, "refunds": [{"refund_id": "r1", "amount_cents": 4900}, {"refund_id": "r2", "amount_cents": 4900}]}, {"refund_total_matches", "refund_count_matches"}),
])
def test_valid_but_incorrect_state_fails_specific_checks(changes, expected_failures):
    evaluation = evaluate_refund(refunded_state() | changes)
    assert evaluation.verdict == "failed"
    assert failed_checks(evaluation) == expected_failures


def test_oracle_does_not_accept_a_self_consistent_wrong_paid_amount():
    state = refunded_state() | {
        "paid_cents": 9800, "refunded_cents": 9800,
        "refunds": [{"refund_id": "r1", "amount_cents": 9800}],
    }
    evaluation = evaluate_refund(state)
    assert evaluation.verdict == "failed"
    assert failed_checks(evaluation) == {"paid_amount_matches", "refund_total_matches"}
    assert evaluation.expected.paid_cents == 4900


@pytest.mark.parametrize("state", [
    None, [], {},
    refunded_state() | {"refunded_cents": "4900"},
    refunded_state() | {"refunded_cents": True},
    refunded_state() | {"refunded_cents": -1},
    refunded_state() | {"refunds": "not-a-ledger"},
    refunded_state() | {"refunds": [{"refund_id": "r1", "amount_cents": False}]},
    refunded_state() | {"refunds": [{"refund_id": "r1", "amount_cents": 0}]},
    refunded_state() | {"unrecognized_state_version": 2},
])
def test_malformed_evidence_is_not_evaluable(state):
    evaluation = evaluate_refund(state)
    assert evaluation.verdict == "not_evaluable"
    assert evaluation.observed is None
    assert failed_checks(evaluation) == {"state_schema"}


def test_evaluation_is_deterministic_and_does_not_mutate_evidence():
    state = refunded_state()
    before = deepcopy(state)
    assert evaluate_refund(state) == evaluate_refund(deepcopy(state))
    assert state == before


def test_claim_only_negative_control_completes_but_fails_task():
    run = execute_agent(ClaimOnlyDemoDriver())
    evaluation = evaluate_refund(run.final_state)
    assert run.status == "completed"
    assert "refunded" in run.output
    assert [step["kind"] for step in run.steps] == ["answer"]
    assert evaluation.verdict == "failed"
    assert evaluation.observed.refund_count == 0


def test_normal_demo_passes_same_evaluator():
    run = execute_agent(DemoDriver())
    assert evaluate_refund(run.final_state).verdict == "passed"
