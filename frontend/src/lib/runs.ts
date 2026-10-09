export interface AgentRun {
  id: string;
  experiment_id: string;
  status: "running" | "completed" | "failed";
  mode: "demo" | "openai";
  model_name: string | null;
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

export function isAgentRun(value: unknown): value is AgentRun {
  if (!isRecord(value)) return false;
  return typeof value.id === "string" && uuid.test(value.id) &&
    typeof value.experiment_id === "string" && uuid.test(value.experiment_id) &&
    ["running", "completed", "failed"].includes(String(value.status)) &&
    (value.mode === "demo" || value.mode === "openai") &&
    (value.model_name === null || typeof value.model_name === "string") &&
    typeof value.task === "string" &&
    (value.output === null || typeof value.output === "string") &&
    (value.error === null || typeof value.error === "string") &&
    Array.isArray(value.steps) && value.steps.every(isRecord) &&
    isRecord(value.initial_state) && isRecord(value.final_state) &&
    isDate(value.started_at) && (value.finished_at === null || isDate(value.finished_at));
}
