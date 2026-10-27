import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { isAgentRun, type AgentRun } from "../src/lib/runs";
import { selectRecordedRun } from "../src/lib/recorded-demo";

const evidence = JSON.parse(readFileSync("public/demo-evidence.json", "utf8"));
const runs = evidence.runs as AgentRun[];

test("public evidence contains nine complete, model-free observations with preserved denominators", () => {
  assert.equal(runs.length, 9);
  assert.equal(new Set(runs.map(run => `${run.scenario}:${run.mode}`)).size, 9);
  assert.ok(runs.every(isAgentRun));
  assert.ok(runs.every(run => run.model_name === null && run.model_telemetry === null && run.trace_id === null));
  assert.equal(evidence.summary.overall.planned, 9);
  assert.equal(evidence.summary.overall.recorded, 9);
  assert.equal(evidence.summary.overall.infrastructure_failed, 0);
});

test("recorded controls preserve the distinction between business state, recovery, and unsupported claims", () => {
  const baseline = selectRecordedRun(runs, "timeout_after_commit", "demo");
  const reconciler = selectRecordedRun(runs, "timeout_after_commit", "demo_reconcile");
  assert.equal(baseline.evaluation?.verdict, "passed");
  assert.equal(reconciler.evaluation?.verdict, "passed");
  assert.equal(baseline.recovery_evaluation?.verdict, "failed");
  assert.equal(reconciler.recovery_evaluation?.verdict, "passed");
  const claim = selectRecordedRun(runs, "timeout_after_commit", "demo_claim_only");
  assert.equal(claim.status, "completed");
  assert.equal(claim.evaluation?.verdict, "failed");
  assert.equal(claim.recovery_evaluation?.verdict, "not_evaluable");
  assert.equal(claim.fault_injected, false);
  assert.throws(() => selectRecordedRun([], "normal", "demo"));
  assert.throws(() => selectRecordedRun([baseline, baseline], "timeout_after_commit", "demo"));
});
