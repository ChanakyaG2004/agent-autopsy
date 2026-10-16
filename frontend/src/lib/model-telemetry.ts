export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cached_input_tokens: number | null;
  cache_write_input_tokens: number | null;
  reasoning_output_tokens: number | null;
}

export interface ModelTelemetry {
  telemetry_version: "openai-responses-v1" | "ollama-chat-v1";
  provider: "openai" | "ollama";
  requested_model: string;
  configuration: Record<string, string | number | boolean | null>;
  attempted_requests: number;
  reported_usage_requests: number;
  usage_complete: boolean;
  known_usage: TokenUsage | null;
  total_request_duration_ms: number;
  requests: Record<string, unknown>[];
}

const record = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const count = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;

function isUsage(v: unknown): v is TokenUsage {
  if (!record(v) || !count(v.input_tokens) || !count(v.output_tokens) || !count(v.total_tokens)) return false;
  return v.input_tokens + v.output_tokens === v.total_tokens &&
    ["cached_input_tokens", "cache_write_input_tokens", "reasoning_output_tokens"].every(key => v[key] === null || count(v[key]));
}

export function isModelTelemetry(v: unknown): v is ModelTelemetry {
  if (!record(v) || !record(v.configuration) || !Array.isArray(v.requests)) return false;
  return ((v.provider === "openai" && v.telemetry_version === "openai-responses-v1") ||
    (v.provider === "ollama" && v.telemetry_version === "ollama-chat-v1")) &&
    typeof v.requested_model === "string" && count(v.attempted_requests) && count(v.reported_usage_requests) &&
    v.reported_usage_requests <= v.attempted_requests && v.requests.length === v.attempted_requests &&
    typeof v.usage_complete === "boolean" &&
    v.usage_complete === (v.attempted_requests > 0 && v.reported_usage_requests === v.attempted_requests) &&
    (v.known_usage === null || isUsage(v.known_usage)) &&
    typeof v.total_request_duration_ms === "number" && Number.isFinite(v.total_request_duration_ms) && v.total_request_duration_ms >= 0 &&
    Object.values(v.configuration).every(value => value === null || typeof value === "string" || typeof value === "boolean" ||
      (typeof value === "number" && Number.isFinite(value))) && v.requests.every(record);
}
