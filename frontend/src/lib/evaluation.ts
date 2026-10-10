export interface RefundExpectation {
  order_id: string;
  currency: string;
  paid_cents: number;
  refunded_cents: number;
  refund_count: number;
}

export interface RefundEvaluation {
  evaluator_version: "refund-ledger-v1";
  verdict: "passed" | "failed" | "not_evaluable";
  expected: RefundExpectation;
  observed: (RefundExpectation & { ledger_total_cents: number }) | null;
  checks: { name: string; passed: boolean; reason: string }[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isExpectation(value: unknown): value is RefundExpectation {
  return isRecord(value) && typeof value.order_id === "string" && typeof value.currency === "string" &&
    Number.isSafeInteger(value.paid_cents) && Number.isSafeInteger(value.refunded_cents) &&
    Number.isSafeInteger(value.refund_count);
}

export function isRefundEvaluation(value: unknown): value is RefundEvaluation {
  if (!isRecord(value)) return false;
  return value.evaluator_version === "refund-ledger-v1" &&
    ["passed", "failed", "not_evaluable"].includes(String(value.verdict)) &&
    isExpectation(value.expected) &&
    (value.observed === null || (isExpectation(value.observed) &&
      "ledger_total_cents" in value.observed && Number.isSafeInteger(value.observed.ledger_total_cents))) &&
    Array.isArray(value.checks) && value.checks.length > 0 && value.checks.every((check: unknown) =>
      isRecord(check) && typeof check.name === "string" && typeof check.passed === "boolean" &&
      typeof check.reason === "string"
    );
}
