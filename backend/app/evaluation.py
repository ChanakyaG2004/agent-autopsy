"""Versioned state-based oracle for the fixed normal refund task.

The evaluator accepts business evidence only, never an agent's final answer.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class RefundEntry(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    refund_id: str = Field(min_length=1)
    amount_cents: int = Field(gt=0)


class RefundState(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    order_id: str = Field(min_length=1)
    paid_cents: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    refunded_cents: int = Field(ge=0)
    refunds: list[RefundEntry]


class RefundExpectation(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    order_id: str
    currency: str
    paid_cents: int
    refunded_cents: int
    refund_count: int


class RefundObservation(RefundExpectation):
    ledger_total_cents: int


class EvaluationCheck(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    name: str
    passed: bool
    reason: str


class RefundEvaluation(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    evaluator_version: Literal["refund-ledger-v1"]
    verdict: Literal["passed", "failed", "not_evaluable"]
    expected: RefundExpectation
    observed: RefundObservation | None
    checks: list[EvaluationCheck]


EXPECTED_REFUND = RefundExpectation(
    order_id="order-123", currency="USD", paid_cents=4900,
    refunded_cents=4900, refund_count=1,
)


def unavailable_evaluation() -> RefundEvaluation:
    return RefundEvaluation(
        evaluator_version="refund-ledger-v1", verdict="not_evaluable",
        expected=EXPECTED_REFUND, observed=None,
        checks=[EvaluationCheck(name="evaluator_error", passed=False,
                                reason="The evaluator could not complete. No task-success verdict was established.")],
    )


def evaluate_refund(final_state: object) -> RefundEvaluation:
    """Do not derive expected values from the potentially incorrect observed state."""
    try:
        state = RefundState.model_validate(final_state)
    except ValidationError:
        return RefundEvaluation(
            evaluator_version="refund-ledger-v1", verdict="not_evaluable",
            expected=EXPECTED_REFUND, observed=None,
            checks=[EvaluationCheck(name="state_schema", passed=False,
                                    reason="Final state is missing or incompatible with refund-ledger-v1.")],
        )

    observed = RefundObservation(
        order_id=state.order_id, currency=state.currency, paid_cents=state.paid_cents,
        refunded_cents=state.refunded_cents, refund_count=len(state.refunds),
        ledger_total_cents=sum(refund.amount_cents for refund in state.refunds),
    )
    comparisons = [
        ("order_matches", observed.order_id, EXPECTED_REFUND.order_id),
        ("currency_matches", observed.currency, EXPECTED_REFUND.currency),
        ("paid_amount_matches", observed.paid_cents, EXPECTED_REFUND.paid_cents),
        ("refund_total_matches", observed.refunded_cents, EXPECTED_REFUND.refunded_cents),
        ("refund_count_matches", observed.refund_count, EXPECTED_REFUND.refund_count),
        ("ledger_consistent", observed.ledger_total_cents, observed.refunded_cents),
    ]
    checks = [EvaluationCheck(
        name=name, passed=actual == expected,
        reason=f"Expected {expected}; observed {actual}.",
    ) for name, actual, expected in comparisons]
    return RefundEvaluation(
        evaluator_version="refund-ledger-v1",
        verdict="passed" if all(check.passed for check in checks) else "failed",
        expected=EXPECTED_REFUND, observed=observed, checks=checks,
    )
