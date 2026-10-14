"""Allowlisted provider measurements. Missing usage is never treated as zero."""

from typing import Literal
import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class TokenUsage(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    cache_write_input_tokens: int | None = Field(default=None, ge=0)
    reasoning_output_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def consistent(self):
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("Inconsistent token total")
        for value, limit in ((self.cached_input_tokens, self.input_tokens),
                             (self.cache_write_input_tokens, self.input_tokens),
                             (self.reasoning_output_tokens, self.output_tokens)):
            if value is not None and value > limit:
                raise ValueError("Token breakdown exceeds its parent count")
        return self


class ModelRequestMeasurement(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    sequence: int = Field(ge=1)
    requested_model: str
    reported_model: str | None
    duration_ms: float = Field(ge=0, allow_inf_nan=False)
    outcome: Literal["response", "error"]
    response_status: Literal["completed", "incomplete", "failed", "cancelled", "queued", "in_progress", "unknown"] | None
    error_type: Literal["timeout", "rate_limit", "authentication", "permission", "connection", "api_error", "unexpected_error"] | None
    usage_status: Literal["reported", "unavailable", "invalid"]
    usage: TokenUsage | None


class ModelRequestConfiguration(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    instructions_sha256: str
    tool_schemas_sha256: str
    max_output_tokens: int
    max_turns: int
    timeout_seconds: float
    max_retries: int
    store: bool
    parallel_tool_calls: bool


class ModelTelemetry(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    telemetry_version: Literal["openai-responses-v1"] = "openai-responses-v1"
    provider: Literal["openai"] = "openai"
    requested_model: str
    configuration: ModelRequestConfiguration
    attempted_requests: int = Field(ge=0)
    reported_usage_requests: int = Field(ge=0)
    usage_complete: bool
    known_usage: TokenUsage | None
    total_request_duration_ms: float = Field(ge=0, allow_inf_nan=False)
    requests: list[ModelRequestMeasurement]


def field(value, name: str):
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def parse_usage(raw) -> tuple[str, TokenUsage | None]:
    if raw is None:
        return "unavailable", None
    try:
        usage = TokenUsage(
            input_tokens=field(raw, "input_tokens"), output_tokens=field(raw, "output_tokens"),
            total_tokens=field(raw, "total_tokens"),
            cached_input_tokens=field(field(raw, "input_tokens_details"), "cached_tokens"),
            cache_write_input_tokens=field(field(raw, "input_tokens_details"), "cache_write_tokens"),
            reasoning_output_tokens=field(field(raw, "output_tokens_details"), "reasoning_tokens"),
        )
        return "reported", usage
    except ValidationError:
        return "invalid", None


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def summarize_requests(model: str, requests: list[ModelRequestMeasurement],
                       configuration: ModelRequestConfiguration) -> ModelTelemetry:
    reported = [request.usage for request in requests if request.usage is not None]
    totals = None
    if reported:
        values = {}
        for name in TokenUsage.model_fields:
            counts = [getattr(usage, name) for usage in reported]
            values[name] = sum(counts) if all(count is not None for count in counts) else None
        totals = TokenUsage(**values)
    return ModelTelemetry(
        requested_model=model, configuration=configuration, attempted_requests=len(requests), reported_usage_requests=len(reported),
        usage_complete=bool(requests) and len(reported) == len(requests), known_usage=totals,
        total_request_duration_ms=sum(request.duration_ms for request in requests),
        requests=list(requests),
    )
