import test from "node:test";
import assert from "node:assert/strict";
import { isGroundingEvaluation, isRefundAnswer, isSecurityEvaluation } from "../src/lib/assurance";

const claim = { answer_version: "refund-answer-v1", order_id: "order-123", outcome: "state", refunded_cents: 0, refund_count: 0, evidence_turn: 1 };
const check = { name: "supported_claim", passed: false, reason: "No supporting response" };

test("typed reports distinguish real zeros from uncertain or denied counts", () => {
  assert.ok(isRefundAnswer(claim));
  assert.ok(isRefundAnswer({ ...claim, outcome: "unknown", refunded_cents: null, refund_count: null }));
  assert.ok(isRefundAnswer({ ...claim, outcome: "denied", refunded_cents: null, refund_count: null }));
  assert.ok(!isRefundAnswer({ ...claim, outcome: "unknown" }));
  assert.ok(!isRefundAnswer({ ...claim, refunded_cents: null }));
  assert.ok(!isRefundAnswer({ ...claim, evidence_turn: true }));
  assert.ok(!isRefundAnswer({ ...claim, evidence_turn: 0 }));
  assert.ok(!isRefundAnswer({ ...claim, refunded_cents: "0" }));
});

test("unavailable grounding and unsupported claims remain separate outcomes", () => {
  assert.ok(isGroundingEvaluation({ evaluator_version: "refund-grounding-v1", verdict: "not_evaluable", claim: null, checks: [check] }));
  assert.ok(isGroundingEvaluation({ evaluator_version: "refund-grounding-v1", verdict: "failed", claim, checks: [check] }));
  assert.ok(!isGroundingEvaluation({ evaluator_version: "future", verdict: "passed", claim, checks: [check] }));
  assert.ok(!isGroundingEvaluation({ evaluator_version: "refund-grounding-v1", verdict: "passed", claim: { ...claim, outcome: "invented" }, checks: [check] }));
});

test("tool-policy evidence requires an explicit verdict, attempt count, and checks", () => {
  const grade = { evaluator_version: "tool-policy-v1", verdict: "failed", attempted_tools: 1, checks: [check] };
  assert.ok(isSecurityEvaluation(grade));
  assert.ok(!isSecurityEvaluation({ ...grade, attempted_tools: -1 }));
  assert.ok(!isSecurityEvaluation({ ...grade, checks: [] }));
  assert.ok(!isSecurityEvaluation({ ...grade, verdict: "safe" }));
});
