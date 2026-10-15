import { isRefundEvaluation, type RefundEvaluation } from "@/lib/evaluation";
import { isRecoveryEvaluation, type RecoveryEvaluation } from "@/lib/recovery";

export type ExecutionMode = "demo" | "demo_claim_only" | "demo_reconcile" | "openai" | "ollama";

export interface AgentRun {
  id: string;
  experiment_id: string;
  status: "running" | "completed" | "failed";
  mode: ExecutionMode;
  scenario: "normal" | "timeout_after_commit" | "permission_denied";
  fault_injected: boolean;
  model_name: string | null;
  trace_id: string | null;
  evaluation: RefundEvaluation | null;
  recovery_evaluation: RecoveryEvaluation | null;
  task: string;
  output: string | null;
  error: string | null;
  steps: Record<string, unknown>[];
  initial_state: Record<string, unknown>;
  final_state: Record<string, unknown>;
  started_at: string;
  finished_at: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const isDate = (value: unknown) => typeof value === "string" && Number.isFinite(Date.parse(value));

const phoenixBaseUrl = (process.env.NEXT_PUBLIC_PHOENIX_BASE_URL ?? "http://127.0.0.1:6006").replace(/\/$/, "");

export function phoenixTraceUrl(traceId: string): string {
  return `${phoenixBaseUrl}/redirects/traces/${encodeURIComponent(traceId)}`;
}

export function isAgentRun(value: unknown): value is AgentRun {
  if (!isRecord(value)) return false;
  return typeof value.id === "string" && uuid.test(value.id) &&
    typeof value.experiment_id === "string" && uuid.test(value.experiment_id) &&
    ["running", "completed", "failed"].includes(String(value.status)) &&
    (value.mode === "demo" || value.mode === "demo_claim_only" || value.mode === "demo_reconcile" || value.mode === "openai" || value.mode === "ollama") &&
    (value.scenario === "normal" || value.scenario === "timeout_after_commit" || value.scenario === "permission_denied") &&
    typeof value.fault_injected === "boolean" &&
    (value.model_name === null || typeof value.model_name === "string") &&
    (value.trace_id === null || (typeof value.trace_id === "string" && /^[0-9a-f]{32}$/.test(value.trace_id))) &&
    (value.evaluation === null || isRefundEvaluation(value.evaluation)) &&
    (value.recovery_evaluation === null || isRecoveryEvaluation(value.recovery_evaluation)) &&
    typeof value.task === "string" &&
    (value.output === null || typeof value.output === "string") &&
    (value.error === null || typeof value.error === "string") &&
    Array.isArray(value.steps) && value.steps.every(isRecord) &&
    isRecord(value.initial_state) && isRecord(value.final_state) &&
    isDate(value.started_at) && (value.finished_at === null || isDate(value.finished_at));
}
