import test from "node:test";
import assert from "node:assert/strict";
import { isBenchmarkRecord, isRunComparison, preferredPair, type RunChoice, type RunComparison } from "../src/lib/comparisons";
import { isAgentRun, type AgentRun } from "../src/lib/runs";
import { isModelTelemetry, type ModelTelemetry } from "../src/lib/model-telemetry";

const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const choice = (n: number, changes: Partial<RunChoice> = {}): RunChoice => ({ id: id(n), experiment_id: id(99),
  experiment_name: "Saved", agent_version: "refund-v1", mode: "ollama", scenario: "normal", status: "completed",
  model_name: "local", started_at: `2026-10-${String(n).padStart(2, "0")}T12:00:00Z`, instructions_sha256: "prompt", ...changes });
const telemetry: ModelTelemetry = { provider: "ollama", telemetry_version: "ollama-chat-v1", requested_model: "local", configuration: {},
  attempted_requests: 1, reported_usage_requests: 1, usage_complete: true, total_request_duration_ms: 0,
  known_usage: { input_tokens: 0, output_tokens: 0, total_tokens: 0, cached_input_tokens: null, cache_write_input_tokens: null, reasoning_output_tokens: null },
  requests: [{}] };
const run = (n: number): AgentRun => ({ ...choice(n), mode: "ollama", scenario: "normal", status: "completed",
  fault_injected: false, trace_id: null, security_evaluation: null, grounding_evaluation: null, evaluation: null, recovery_evaluation: null, model_telemetry: telemetry,
  task: "Refund", output: null, error: null, steps: [], initial_state: {}, final_state: {}, finished_at: "2026-10-19T12:00:00Z" });

test("default pair prefers a comparable model scenario over newer scripts, faults, and running attempts", () => {
  const rows = [choice(8, { mode: "demo" }), choice(7, { scenario: "permission_denied" }),
    choice(6, { status: "running" }), choice(5), choice(4, { agent_version: "other" }), choice(3)];
  assert.deepEqual(preferredPair(rows), [id(3), id(5)]);
  assert.equal(preferredPair([choice(1)]), null);
  assert.equal(preferredPair([choice(2, { status: "running" }), choice(1)]), null);
});

test("fallback pair retains different cases for explicit mismatch reporting", () => {
  assert.deepEqual(preferredPair([choice(2, { scenario: "permission_denied" }), choice(1)]), [id(1), id(2)]);
});

test("interrupted observations never become the default terminal comparison pair", () => {
  assert.deepEqual(preferredPair([choice(3, { status: "interrupted" }), choice(2), choice(1)]), [id(1), id(2)]);
});

test("zero usage is real evidence; unknown usage stays null and incomplete", () => {
  assert.ok(isModelTelemetry(telemetry));
  assert.ok(isAgentRun(run(1)));
  assert.ok(isModelTelemetry({ ...telemetry, reported_usage_requests: 0, usage_complete: false, known_usage: null }));
  assert.ok(!isModelTelemetry({ ...telemetry, reported_usage_requests: 0 }));
  assert.ok(!isModelTelemetry({ ...telemetry, known_usage: { ...telemetry.known_usage, total_tokens: 3 } }));
  assert.ok(!isModelTelemetry({ ...telemetry, provider: "openai" }));
  assert.ok(!isModelTelemetry({ ...telemetry, total_request_duration_ms: Infinity }));
});

test("comparison contract preserves unavailable deltas and rejects malformed evidence", () => {
  const report: RunComparison = { comparison_version: "recorded-runs-v2", baseline: { experiment_name: "Earlier", agent_version: "refund-v1", run: run(1) },
    candidate: { experiment_name: "Later", agent_version: "refund-v1", run: run(2) }, outcomes_comparable: false, recovery_comparable: false,
    security_comparable: false, grounding_comparable: false, tokens_comparable: false, request_measurements_comparable: true, checks: [], configuration_changes: [],
    measurements: [{ field: "total_tokens", unit: "tokens", baseline: 0, candidate: null, delta: null }], notes: ["One observation per side."] };
  assert.ok(isRunComparison(report));
  assert.ok(!isRunComparison({ ...report, comparison_version: "future" }));
  assert.ok(!isRunComparison({ ...report, measurements: [{ ...report.measurements[0], delta: NaN }] }));
  assert.ok(!isRunComparison({ ...report, candidate: { ...report.candidate, run: { ...run(2), id: "broken" } } }));
});

test("benchmark counts cannot silently lose planned work or invent extra grades", () => {
  const counts = { planned: 9, recorded: 8, infrastructure_failed: 1, pending: 0, execution_completed: 6, execution_failed: 2,
    ledger_passed: 4, ledger_failed: 4, ledger_not_evaluable: 0, recovery_passed: 2, recovery_failed: 2,
    recovery_not_evaluable: 2, recovery_not_applicable: 2, fault_selected: 6, fault_injected: 4 };
  const report = { id: id(1), suite_version: "refund-resilience-v1", status: "failed", started_at: choice(1).started_at, finished_at: choice(2).started_at,
    summary: { summary_version: "benchmark-counts-v1", overall: counts, drivers: [] } };
  assert.ok(isBenchmarkRecord(report));
  assert.ok(!isBenchmarkRecord({ ...report, summary: { ...report.summary, overall: { ...counts, infrastructure_failed: 0 } } }));
  assert.ok(!isBenchmarkRecord({ ...report, summary: { ...report.summary, overall: { ...counts, ledger_passed: 9 } } }));
  assert.ok(!isBenchmarkRecord({ ...report, summary: { ...report.summary, overall: { ...counts, fault_injected: 7 } } }));
});
