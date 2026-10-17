"""Read-only comparisons of recorded evidence; never rerun or regrade an agent."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evaluation import EvaluationCheck
from app.models import AgentRun, Experiment
from app.schemas import RunRead


class RunChoice(BaseModel):
    id: UUID
    experiment_id: UUID
    experiment_name: str
    agent_version: str
    mode: str
    scenario: str
    status: str
    model_name: str | None
    started_at: datetime
    instructions_sha256: str | None


class ComparisonSide(BaseModel):
    experiment_name: str
    agent_version: str
    run: RunRead


class ConfigurationChange(BaseModel):
    field: str
    baseline: str | int | float | bool | None
    candidate: str | int | float | bool | None


class MeasurementDelta(BaseModel):
    field: str
    unit: Literal["ms", "tokens", "requests"]
    baseline: float | None
    candidate: float | None
    delta: float | None


class RunComparison(BaseModel):
    comparison_version: Literal["recorded-runs-v2"] = "recorded-runs-v2"
    baseline: ComparisonSide
    candidate: ComparisonSide
    outcomes_comparable: bool
    security_comparable: bool
    grounding_comparable: bool
    recovery_comparable: bool
    tokens_comparable: bool
    request_measurements_comparable: bool
    checks: list[EvaluationCheck]
    configuration_changes: list[ConfigurationChange]
    measurements: list[MeasurementDelta]
    notes: list[str]


def run_choices(session: Session, limit: int, offset: int) -> list[RunChoice]:
    rows = session.execute(select(AgentRun, Experiment).join(Experiment)
                           .order_by(AgentRun.started_at.desc(), AgentRun.id.desc()).limit(limit).offset(offset))
    choices = []
    for run, experiment in rows:
        data = run.model_telemetry or {}
        configuration = data.get("configuration") or {}
        choices.append(RunChoice(
            id=run.id, experiment_id=experiment.id, experiment_name=experiment.name,
            agent_version=experiment.agent_version, mode=run.mode, scenario=run.scenario,
            status=run.status, model_name=run.model_name, started_at=run.started_at,
            instructions_sha256=configuration.get("instructions_sha256"),
        ))
    return choices


def compare_sides(baseline: ComparisonSide, candidate: ComparisonSide) -> RunComparison:
    left, right = baseline.run, candidate.run
    checks = []

    def check(name: str, passed: bool, reason: str) -> bool:
        checks.append(EvaluationCheck(name=name, passed=passed, reason=reason))
        return passed

    same_case = all([
        check("same_task", left.task == right.task, "Task instructions must match."),
        check("same_agent_contract", baseline.agent_version == candidate.agent_version,
              "Agent task-contract labels must match; provider and prompt changes are shown separately."),
        check("same_scenario", left.scenario == right.scenario, "Fault scenarios must match."),
        check("same_initial_state", left.initial_state == right.initial_state, "Business starting states must match."),
        check("terminal_evidence", left.status != "running" and right.status != "running",
              "Both executions must have terminal results."),
    ])
    ledger_known = check("ledger_evidence", bool(
        left.evaluation and right.evaluation
        and left.evaluation.verdict in {"passed", "failed"} and right.evaluation.verdict in {"passed", "failed"}
        and left.evaluation.evaluator_version == right.evaluation.evaluator_version
        and left.evaluation.expected == right.evaluation.expected),
        "Both ledger grades must be available with the same evaluator version and expectation.")
    recovery_known = check("recovery_evidence", bool(
        left.recovery_evaluation and right.recovery_evaluation
        and left.recovery_evaluation.verdict in {"passed", "failed"}
        and right.recovery_evaluation.verdict in {"passed", "failed"}
        and left.recovery_evaluation.evaluator_version == right.recovery_evaluation.evaluator_version
        and left.scenario != "normal" and left.fault_injected and right.fault_injected),
        "Recovery comparison requires matching graded policies and actual fault exercise on both sides. Normal runs are not recovery tests.")
    assurance_flags = {}
    for name in ("security", "grounding"):
        x, y = getattr(left, f"{name}_evaluation"), getattr(right, f"{name}_evaluation")
        assurance_flags[name] = same_case and check(f"{name}_evidence", bool(
            x and y and x.verdict in {"passed", "failed"} and y.verdict in {"passed", "failed"}
            and x.evaluator_version == y.evaluator_version),
            f"Both {name} grades must be available with the same evaluator version.")
    a, b = left.model_telemetry, right.model_telemetry
    measured = check("request_measurements", bool(a and b and a.attempted_requests and b.attempted_requests),
                     "Both sides need recorded model requests; scripted or historical runs have no model timing/usage.")
    complete_usage = check("complete_usage", bool(a and b and a.usage_complete and b.usage_complete
                                                 and a.known_usage and b.known_usage),
                           "Token deltas require complete core usage on both sides, not partial subtotals.")
    same_model = False
    if a and b and a.requests and b.requests:
        a_models = {request.reported_model for request in a.requests}
        b_models = {request.reported_model for request in b.requests}
        same_model = (a.provider == b.provider and len(a_models) == 1 and a_models == b_models
                      and all(a_models) and (a.provider != "ollama" or bool(
                          a.configuration.model_digest and a.configuration.model_digest == b.configuration.model_digest)))
    check("same_model_identity", same_model,
          "Token deltas require the same provider and one matching reported model; Ollama also requires matching nonempty weight digests.")
    token_eligible = same_case and complete_usage and same_model
    request_eligible = same_case and measured

    def configuration(side: ComparisonSide) -> dict:
        run = side.run
        values = {"driver": run.mode, "model": run.model_name, "agent_contract": side.agent_version,
                  "scenario": run.scenario}
        telemetry = run.model_telemetry
        values["provider"] = telemetry.provider if telemetry else None
        values["telemetry_version"] = telemetry.telemetry_version if telemetry else None
        values.update({f"request.{key}": value for key, value in (
            telemetry.configuration.model_dump().items() if telemetry else [])})
        return values

    left_config, right_config = configuration(baseline), configuration(candidate)
    changes = [ConfigurationChange(field=key, baseline=left_config.get(key), candidate=right_config.get(key))
               for key in sorted(left_config.keys() | right_config.keys()) if left_config.get(key) != right_config.get(key)]
    measurements = []
    for field, unit, x, y, eligible in [
        ("request_time", "ms", a.total_request_duration_ms if a else None, b.total_request_duration_ms if b else None, request_eligible),
        ("model_requests", "requests", a.attempted_requests if a else None, b.attempted_requests if b else None, request_eligible),
        *[(field, "tokens", getattr(a.known_usage, field) if a and a.known_usage else None,
           getattr(b.known_usage, field) if b and b.known_usage else None, token_eligible)
          for field in ("input_tokens", "output_tokens", "total_tokens")],
    ]:
        measurements.append(MeasurementDelta(field=field, unit=unit, baseline=x, candidate=y,
                                             delta=y - x if eligible and x is not None and y is not None else None))
    return RunComparison(
        baseline=baseline, candidate=candidate, outcomes_comparable=same_case and ledger_known,
        recovery_comparable=same_case and recovery_known, tokens_comparable=token_eligible,
        security_comparable=assurance_flags["security"], grounding_comparable=assurance_flags["grounding"],
        request_measurements_comparable=request_eligible, checks=checks, configuration_changes=changes,
        measurements=measurements, notes=[
            "This is one recorded observation per side, not a reliability rate or proof of general improvement.",
            "Tool-policy grades audit attempted sandbox actions, not general security. Grounding grades check only the typed refund report against agent-visible tool responses, not arbitrary prose.",
            "Request time is client-observed across all attempts. Loading, caching, hardware, request count, and failures can differ; no speedup claim is inferred.",
            "Token values are known subtotals when usage is incomplete. Suppressed deltas are unavailable, not zero. No dollar cost or semantic answer score is calculated.",
        ],
    )


def compare_runs(baseline_id: UUID, candidate_id: UUID, session: Session) -> RunComparison:
    if baseline_id == candidate_id:
        raise HTTPException(422, "Choose two different recorded runs.")
    rows = session.execute(select(AgentRun, Experiment).join(Experiment)
                           .where(AgentRun.id.in_([baseline_id, candidate_id])))
    sides = {run.id: ComparisonSide(experiment_name=experiment.name, agent_version=experiment.agent_version,
                                   run=RunRead.model_validate(run)) for run, experiment in rows}
    if baseline_id not in sides or candidate_id not in sides:
        raise HTTPException(404, "Comparison run not found")
    return compare_sides(sides[baseline_id], sides[candidate_id])
