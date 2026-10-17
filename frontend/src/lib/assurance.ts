export interface RefundAnswer {
  answer_version: "refund-answer-v1";
  order_id: string;
  outcome: "state" | "denied" | "unknown";
  refunded_cents: number | null;
  refund_count: number | null;
  evidence_turn: number;
}
type Check = { name: string; passed: boolean; reason: string };
type Verdict = "passed" | "failed" | "not_evaluable";
export interface SecurityEvaluation { evaluator_version: "tool-policy-v1" | "tool-policy-v2"; verdict: Verdict; attempted_tools: number; checks: Check[] }
export interface GroundingEvaluation { evaluator_version: "refund-grounding-v1"; verdict: Verdict; claim: RefundAnswer | null; checks: Check[] }

const record = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const count = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
function grade(v: unknown): v is Record<string, unknown> {
  return record(v) && ["passed", "failed", "not_evaluable"].includes(String(v.verdict)) && Array.isArray(v.checks) && v.checks.length > 0 &&
    v.checks.every(c => record(c) && typeof c.name === "string" && typeof c.passed === "boolean" && typeof c.reason === "string");
}
export function isRefundAnswer(v: unknown): v is RefundAnswer {
  return record(v) && v.answer_version === "refund-answer-v1" && typeof v.order_id === "string" &&
    ["state", "denied", "unknown"].includes(String(v.outcome)) && count(v.evidence_turn) && v.evidence_turn > 0 &&
    (v.outcome === "state" ? count(v.refunded_cents) && count(v.refund_count) : v.refunded_cents === null && v.refund_count === null);
}
export function isSecurityEvaluation(v: unknown): v is SecurityEvaluation {
  return grade(v) && ["tool-policy-v1", "tool-policy-v2"].includes(String(v.evaluator_version)) && count(v.attempted_tools);
}
export function isGroundingEvaluation(v: unknown): v is GroundingEvaluation {
  return grade(v) && v.evaluator_version === "refund-grounding-v1" && (v.claim === null || isRefundAnswer(v.claim));
}
