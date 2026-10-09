export type Scenario = "normal" | "timeout_after_commit" | "permission_denied";

export interface ExperimentDraft {
  name: string;
  agent_version: string;
  scenarios: Scenario[];
}

export interface SavedExperiment extends ExperimentDraft {
  id: string;
  status: "draft" | "running" | "completed" | "failed";
  created_at: string;
}

export const apiBaseUrl = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

export function isSavedExperiment(value: unknown): value is SavedExperiment {
  if (typeof value !== "object" || value === null) return false;
  return (
    "id" in value && typeof value.id === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value.id) &&
    "name" in value && typeof value.name === "string" &&
    "agent_version" in value && typeof value.agent_version === "string" &&
    "status" in value && ["draft", "running", "completed", "failed"].includes(String(value.status)) &&
    "created_at" in value && typeof value.created_at === "string" &&
    Number.isFinite(Date.parse(value.created_at)) &&
    "scenarios" in value && Array.isArray(value.scenarios) &&
    value.scenarios.length >= 1 && value.scenarios.length <= 3 &&
    value.scenarios.every((scenario: unknown) =>
      scenario === "normal" || scenario === "timeout_after_commit" || scenario === "permission_denied"
    ) && new Set(value.scenarios).size === value.scenarios.length
  );
}
