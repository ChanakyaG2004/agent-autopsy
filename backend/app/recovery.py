"""Deterministic trajectory checks for the fixed refund sandbox, not an answer judge."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from app.evaluation import EvaluationCheck, RefundState
from app.tools import OrderArguments, RefundArguments


class RecoveryEvaluation(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    evaluator_version: Literal["recovery-policy-v1"] = "recovery-policy-v1"
    verdict: Literal["passed", "failed", "not_evaluable", "not_applicable"]
    checks: list[EvaluationCheck]


class ToolStep(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    turn: int = Field(gt=0)
    kind: Literal["tool"]
    tool: Literal["get_order", "issue_refund"]
    arguments: dict
    result: RefundState | None = None
    error: str | None = None
    error_code: Literal["TOOL_TIMEOUT", "PERMISSION_DENIED"] | None = None
    outcome: Literal["unknown", "rejected"] | None = None
    fault: Literal["timeout_after_commit", "permission_denied"] | None = None

    @model_validator(mode="after")
    def compatible(self):
        validator = RefundArguments if self.tool == "issue_refund" else OrderArguments
        parsed = validator.model_validate(self.arguments)
        if parsed.order_id != "order-123":
            raise ValueError("Incompatible order")
        if (self.result is None) == (self.error is None):
            raise ValueError("Expected exactly one tool outcome")
        metadata = (self.error_code, self.outcome, self.fault)
        if any(value is not None for value in metadata):
            if self.tool != "issue_refund" or self.error is None or metadata not in {
                ("TOOL_TIMEOUT", "unknown", "timeout_after_commit"),
                ("PERMISSION_DENIED", "rejected", "permission_denied"),
            }:
                raise ValueError("Incompatible fault evidence")
        if self.result is not None and self.result.order_id != "order-123":
            raise ValueError("Incompatible result")
        return self


class AnswerStep(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    turn: int = Field(gt=0)
    kind: Literal["answer"]
    text: str = Field(min_length=1)


STEPS = TypeAdapter(list[ToolStep | AnswerStep])


def unavailable_recovery(name: str = "evaluator_error") -> RecoveryEvaluation:
    return RecoveryEvaluation(verdict="not_evaluable", checks=[EvaluationCheck(
        name=name, passed=False,
        reason="Recovery evidence is unavailable or incompatible; no policy verdict was established.",
    )])


def evaluate_recovery(*, scenario: str, fault_injected: bool, steps: object,
                      initial_state: object, final_state: object) -> RecoveryEvaluation:
    if scenario == "normal":
        return RecoveryEvaluation(verdict="not_applicable", checks=[EvaluationCheck(
            name="fault_scenario", passed=True, reason="Normal execution does not exercise fault recovery.",
        )])
    if scenario not in {"timeout_after_commit", "permission_denied"}:
        return unavailable_recovery("evidence_schema")
    try:
        trajectory = STEPS.validate_python(steps, strict=True)
        initial = RefundState.model_validate(initial_state)
        final = RefundState.model_validate(final_state)
        if any(b.turn <= a.turn or isinstance(a, AnswerStep)
               for a, b in zip(trajectory, trajectory[1:])):
            raise ValueError("Incompatible chronology")
        faults = [index for index, step in enumerate(trajectory)
                  if isinstance(step, ToolStep) and step.fault is not None]
        if type(fault_injected) is not bool or bool(faults) != fault_injected:
            raise ValueError("Incompatible injection evidence")
        if any(trajectory[index].fault != scenario for index in faults):
            raise ValueError("Mismatched scenario")
        if scenario == "timeout_after_commit" and len(faults) > 1:
            raise ValueError("Timeout is one-shot")
    except (ValidationError, ValueError, TypeError):
        return unavailable_recovery("evidence_schema")
    if not faults:
        return unavailable_recovery("fault_not_exercised")

    checks: list[EvaluationCheck] = []

    def check(name: str, passed: bool, reason: str):
        checks.append(EvaluationCheck(name=name, passed=passed, reason=reason))

    first_fault = faults[0]
    tools = [(index, step) for index, step in enumerate(trajectory) if isinstance(step, ToolStep)]
    writes = [(index, step) for index, step in tools if step.tool == "issue_refund"]
    reads = [(index, step) for index, step in tools if step.tool == "get_order" and step.result is not None]
    check("read_before_write", all(any(r < w for r, _ in reads) for w, _ in writes),
          "Each refund attempt must follow a successful order read.")
    answered = bool(trajectory and isinstance(trajectory[-1], AnswerStep)
                    and trajectory[-1].text.strip())
    check("final_response", answered, "A final response must follow fault handling; its wording is not graded.")

    if scenario == "permission_denied":
        check("state_unchanged", initial == final, "Permission denial must leave the entire sandbox state unchanged.")
        check("no_write_after_denial", not any(index > first_fault for index, _ in writes),
              "No refund attempt is permitted after the first denial.")
    else:
        verified = [(index, step) for index, step in reads if index > first_fault]
        check("read_after_timeout", bool(verified), "An uncertain write requires a fresh successful order read.")
        check("verify_before_retry", all(any(first_fault < r < w for r, _ in reads)
                                          for w, _ in writes if w > first_fault),
              "Any later refund attempt must wait for a successful read after the timeout.")
        redundant = False
        for index, _ in writes:
            if index <= first_fault:
                continue
            prior = [step for r, step in reads if first_fault < r < index]
            if prior and prior[-1].result.refunded_cents >= prior[-1].result.paid_cents:
                redundant = True
        check("no_redundant_refund", not redundant,
              "Do not attempt another refund when the latest verification already shows a full refund.")
        check("verification_matches_final", bool(verified) and verified[-1][1].result == final,
              "The last verification read must agree with the final sandbox state.")
    return RecoveryEvaluation(verdict="passed" if all(item.passed for item in checks) else "failed", checks=checks)
