import { isAgentRun, type AgentRun } from "./runs";

export const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const uuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);
const date = (v: unknown): v is string => typeof v === "string" && Number.isFinite(Date.parse(v));
const nullableString = (v: unknown): v is string | null => v === null || typeof v === "string";
const count = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const nullableNumber = (v: unknown): v is number | null => v === null || (typeof v === "number" && Number.isFinite(v));

export interface RunChoice {
  id: string; experiment_id: string; experiment_name: string; agent_version: string;
  mode: string; scenario: string; status: string; model_name: string | null;
  started_at: string; instructions_sha256: string | null;
}
export interface ComparisonSide { experiment_name: string; agent_version: string; run: AgentRun }
export interface RunComparison {
  comparison_version: "recorded-runs-v1";
  baseline: ComparisonSide; candidate: ComparisonSide;
  outcomes_comparable: boolean; recovery_comparable: boolean;
  tokens_comparable: boolean; request_measurements_comparable: boolean;
  checks: { name: string; passed: boolean; reason: string }[];
  configuration_changes: { field: string; baseline: string | number | boolean | null; candidate: string | number | boolean | null }[];
  measurements: { field: string; unit: "ms" | "tokens" | "requests"; baseline: number | null; candidate: number | null; delta: number | null }[];
  notes: string[];
}

export function isRunChoice(v: unknown): v is RunChoice {
  return isRecord(v) && uuid(v.id) && uuid(v.experiment_id) && typeof v.experiment_name === "string" &&
    typeof v.agent_version === "string" && ["demo", "demo_reconcile", "demo_claim_only", "ollama", "openai"].includes(String(v.mode)) &&
    ["normal", "timeout_after_commit", "permission_denied"].includes(String(v.scenario)) &&
    ["running", "completed", "failed"].includes(String(v.status)) && nullableString(v.model_name) &&
    date(v.started_at) && nullableString(v.instructions_sha256);
}

function isSide(v: unknown): v is ComparisonSide {
  return isRecord(v) && typeof v.experiment_name === "string" && typeof v.agent_version === "string" && isAgentRun(v.run);
}

export function isRunComparison(v: unknown): v is RunComparison {
  return isRecord(v) && v.comparison_version === "recorded-runs-v1" && isSide(v.baseline) && isSide(v.candidate) &&
    ["outcomes_comparable", "recovery_comparable", "tokens_comparable", "request_measurements_comparable"].every(key => typeof v[key] === "boolean") &&
    Array.isArray(v.checks) && v.checks.every(c => isRecord(c) && typeof c.name === "string" && typeof c.passed === "boolean" && typeof c.reason === "string") &&
    Array.isArray(v.configuration_changes) && v.configuration_changes.every(c => isRecord(c) && typeof c.field === "string" &&
      [c.baseline, c.candidate].every(value => value === null || typeof value === "string" || typeof value === "boolean" || nullableNumber(value))) &&
    Array.isArray(v.measurements) && v.measurements.every(m => isRecord(m) && typeof m.field === "string" &&
      ["ms", "tokens", "requests"].includes(String(m.unit)) && nullableNumber(m.baseline) && nullableNumber(m.candidate) && nullableNumber(m.delta)) &&
    Array.isArray(v.notes) && v.notes.every(note => typeof note === "string");
}

export const countKeys = ["planned", "recorded", "infrastructure_failed", "pending", "execution_completed", "execution_failed",
  "ledger_passed", "ledger_failed", "ledger_not_evaluable", "recovery_passed", "recovery_failed", "recovery_not_evaluable",
  "recovery_not_applicable", "fault_selected", "fault_injected"] as const;
export type BenchmarkCounts = Record<typeof countKeys[number], number>;
export interface BenchmarkSummary { summary_version: "benchmark-counts-v1"; overall: BenchmarkCounts;
  drivers: { mode: string; counts: BenchmarkCounts }[] }
export interface BenchmarkRecord { id: string; suite_version: string; status: string; started_at: string;
  finished_at: string | null; summary: BenchmarkSummary }
export interface BenchmarkDetail extends BenchmarkRecord { manifest: Record<string, unknown>;
  items: { id: string; experiment_id: string; run_id: string | null; position: number; case_key: string;
    mode: string; repetition: number; status: string; error: string | null; run: AgentRun | null }[] }

function isCounts(v: unknown): v is BenchmarkCounts {
  if (!isRecord(v) || !countKeys.every(key => count(v[key]))) return false;
  const c = v as BenchmarkCounts;
  return c.recorded + c.infrastructure_failed + c.pending === c.planned &&
    c.execution_completed + c.execution_failed === c.recorded &&
    c.ledger_passed + c.ledger_failed + c.ledger_not_evaluable === c.recorded &&
    c.recovery_passed + c.recovery_failed + c.recovery_not_evaluable + c.recovery_not_applicable === c.recorded &&
    c.fault_injected <= c.fault_selected && c.fault_selected <= c.planned;
}

export function isBenchmarkRecord(v: unknown): v is BenchmarkRecord {
  if (!isRecord(v) || !isRecord(v.summary)) return false;
  return uuid(v.id) && typeof v.suite_version === "string" && ["running", "completed", "failed"].includes(String(v.status)) &&
    date(v.started_at) && (v.finished_at === null || date(v.finished_at)) &&
    v.summary.summary_version === "benchmark-counts-v1" && isCounts(v.summary.overall) &&
    Array.isArray(v.summary.drivers) && v.summary.drivers.every(group => isRecord(group) &&
      ["demo", "demo_reconcile", "demo_claim_only"].includes(String(group.mode)) && isCounts(group.counts));
}

export function isBenchmarkDetail(v: unknown): v is BenchmarkDetail {
  return isBenchmarkRecord(v) && "manifest" in v && isRecord(v.manifest) && "items" in v &&
    Array.isArray(v.items) && v.items.every(item => isRecord(item) && uuid(item.id) && uuid(item.experiment_id) &&
      (item.run_id === null || uuid(item.run_id)) && count(item.position) && typeof item.case_key === "string" &&
      ["demo", "demo_reconcile", "demo_claim_only"].includes(String(item.mode)) && count(item.repetition) &&
      ["pending", "running", "completed", "failed"].includes(String(item.status)) && nullableString(item.error) &&
      (item.run === null || isAgentRun(item.run)));
}

export function preferredPair(runs: RunChoice[]): [string, string] | null {
  const terminal = runs.filter(run => run.status !== "running");
  const models = terminal.filter(run => run.mode === "ollama" || run.mode === "openai");
  for (const group of [models, terminal]) {
    for (const candidate of group) {
      const baseline = group.find(run => run.id !== candidate.id && run.mode === candidate.mode &&
        run.scenario === candidate.scenario && run.agent_version === candidate.agent_version &&
        Date.parse(run.started_at) <= Date.parse(candidate.started_at));
      if (baseline) return [baseline.id, candidate.id];
    }
  }
  return terminal.length >= 2 ? [terminal[1].id, terminal[0].id] : null;
}
