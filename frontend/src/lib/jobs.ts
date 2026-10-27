import { apiBaseUrl } from "./experiments";

export interface Job {
  job_version: "durable-jobs-v1";
  id: string; request_id: string; kind: "run" | "benchmark";
  status: "queued" | "running" | "succeeded" | "failed" | "interrupted";
  experiment_id: string | null; run_id: string | null; benchmark_id: string | null;
  attempts: number; worker_id: string | null; lease_expires_at: string | null; error: string | null;
  created_at: string; started_at: string | null; finished_at: string | null;
}
const record = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const uuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);
const date = (v: unknown): v is string => typeof v === "string" && Number.isFinite(Date.parse(v));
const nullableDate = (v: unknown) => v === null || date(v);
const nullableString = (v: unknown) => v === null || typeof v === "string";
export const jobActive = (job: Job | null) => job?.status === "queued" || job?.status === "running";

export function isJob(v: unknown): v is Job {
  if (!record(v) || v.job_version !== "durable-jobs-v1" || !uuid(v.id) || !uuid(v.request_id)) return false;
  const active = v.status === "queued" || v.status === "running";
  return ["queued", "running", "succeeded", "failed", "interrupted"].includes(String(v.status)) &&
    (v.kind === "run" ? uuid(v.experiment_id) && uuid(v.run_id) && v.benchmark_id === null
      : v.kind === "benchmark" && v.experiment_id === null && v.run_id === null && uuid(v.benchmark_id)) &&
    typeof v.attempts === "number" && Number.isSafeInteger(v.attempts) && v.attempts >= 0 && v.attempts <= 3 &&
    nullableString(v.worker_id) && nullableString(v.error) && date(v.created_at) && nullableDate(v.started_at) &&
    (active ? v.finished_at === null : date(v.finished_at)) &&
    (v.status === "running" ? date(v.lease_expires_at) : v.lease_expires_at === null);
}

export function submissionBody(previous: unknown, fields: Record<string, string | number>, freshId: string): Record<string, string | number> {
  if (!uuid(freshId)) throw new Error("Invalid request identity.");
  if (previous === null) return { ...fields, request_id: freshId };
  if (!record(previous) || !uuid(previous.request_id) || Object.keys(previous).length !== Object.keys(fields).length + 1 ||
    !Object.entries(fields).every(([key, value]) => previous[key] === value)) {
    throw new Error("An earlier submission is unconfirmed with different settings. Refresh jobs and restore the previously selected driver before retrying.");
  }
  return { ...fields, request_id: previous.request_id };
}

export async function submitJob(path: string, fields: Record<string, string | number>, storageKey: string): Promise<Job> {
  let body: Record<string, string | number>;
  try {
    const saved = localStorage.getItem(storageKey);
    body = submissionBody(saved === null ? null : JSON.parse(saved), fields, crypto.randomUUID());
    localStorage.setItem(storageKey, JSON.stringify(body));
  } catch (error) {
    throw new Error(error instanceof Error ? error.message : "Could not save submission tracking in this browser.");
  }
  const response = await fetch(`${apiBaseUrl}${path}`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body), signal: AbortSignal.timeout(10_000) });
  const result: unknown = await response.json();
  if (!response.ok || !isJob(result) || result.request_id !== body.request_id ||
      ("mode" in fields ? result.kind !== "run" || path !== `/experiments/${result.experiment_id}/jobs` : result.kind !== "benchmark")) {
    const message = record(result) && typeof result.detail === "string" ? result.detail : "Could not confirm job acceptance.";
    if (response.status >= 400 && response.status < 500) localStorage.removeItem(storageKey);
    throw new Error(`${message} Refresh jobs before submitting again.`);
  }
  localStorage.removeItem(storageKey);
  return result;
}
