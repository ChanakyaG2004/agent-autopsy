import type { AgentRun, ExecutionMode } from "./runs";
import type { Scenario } from "./experiments";

export type ScriptedMode = Extract<ExecutionMode, "demo" | "demo_reconcile" | "demo_claim_only">;

export const policyNames: Record<ScriptedMode, string> = {
  demo: "Baseline",
  demo_reconcile: "Reconcile",
  demo_claim_only: "Claim only",
};

export const scenarioNames: Record<Scenario, string> = {
  normal: "Normal operation",
  timeout_after_commit: "Response lost after refund",
  permission_denied: "Permission denied",
};

export function selectRecordedRun(runs: AgentRun[], scenario: Scenario, mode: ScriptedMode): AgentRun {
  const matches = runs.filter(run => run.scenario === scenario && run.mode === mode);
  if (matches.length !== 1) throw new Error("Recorded evidence is missing or ambiguous.");
  return matches[0];
}

export function verdictLabel(verdict: string | undefined): string {
  if (verdict === "passed") return "Passed";
  if (verdict === "failed") return "Failed";
  if (verdict === "not_applicable") return "Not applicable";
  return "Not evaluable";
}
