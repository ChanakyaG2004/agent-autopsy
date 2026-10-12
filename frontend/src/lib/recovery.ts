export interface RecoveryEvaluation {
  evaluator_version: "recovery-policy-v1";
  verdict: "passed" | "failed" | "not_evaluable" | "not_applicable";
  checks: { name: string; passed: boolean; reason: string }[];
}

export function isRecoveryEvaluation(value: unknown): value is RecoveryEvaluation {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const item = value as Record<string, unknown>;
  return item.evaluator_version === "recovery-policy-v1" &&
    ["passed", "failed", "not_evaluable", "not_applicable"].includes(String(item.verdict)) &&
    Array.isArray(item.checks) && item.checks.length > 0 && item.checks.every((check: unknown) =>
      typeof check === "object" && check !== null && !Array.isArray(check) &&
      "name" in check && typeof check.name === "string" &&
      "passed" in check && typeof check.passed === "boolean" &&
      "reason" in check && typeof check.reason === "string");
}
