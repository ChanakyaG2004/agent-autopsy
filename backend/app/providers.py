import json
import os
from time import perf_counter_ns
from copy import deepcopy

from openai import (APIConnectionError, APIError, APITimeoutError, AuthenticationError,
                    OpenAI, PermissionDeniedError, RateLimitError)
from openinference.semconv.trace import SpanAttributes

from app.agent import AgentError, ClaimOnlyDemoDriver, DemoDriver, INSTRUCTIONS, MAX_TURNS, ModelTurn, ReconcileDemoDriver, ToolCall
from app.tools import TOOL_SCHEMAS
from app.telemetry import span
from app.model_telemetry import (ModelRequestConfiguration, ModelRequestMeasurement,
                                 ModelTelemetry, fingerprint, parse_usage, summarize_requests)


class ProviderNotConfigured(Exception):
    pass


class OpenAIDriver:
    def __init__(self, api_key: str, model: str):
        self.model = model
        self.instructions = INSTRUCTIONS
        self.tools = deepcopy(TOOL_SCHEMAS)
        self.configuration = ModelRequestConfiguration(
            instructions_sha256=fingerprint(self.instructions), tool_schemas_sha256=fingerprint(self.tools),
            max_output_tokens=1024, max_turns=MAX_TURNS, timeout_seconds=10.0,
            max_retries=0, store=False, parallel_tool_calls=False,
        )
        self.requests: list[ModelRequestMeasurement] = []
        self.client = OpenAI(api_key=api_key, timeout=self.configuration.timeout_seconds,
                             max_retries=self.configuration.max_retries)

    @property
    def model_telemetry(self) -> ModelTelemetry:
        return summarize_requests(self.model, self.requests, self.configuration)

    def decide(self, history: list[dict]) -> ModelTurn:
        with span("openai.responses", "LLM", **{
            "llm.system": "openai", "llm.provider": "openai", "llm.model_name": self.model,
            "agent.requested_model": self.model,
        }) as current:
            return self._request(history, current)

    def _request(self, history: list[dict], current) -> ModelTurn:
        started = perf_counter_ns()
        try:
            response = self.client.responses.create(
                model=self.model, instructions=self.instructions, input=history,
                tools=self.tools, parallel_tool_calls=self.configuration.parallel_tool_calls,
                store=self.configuration.store,
                include=["reasoning.encrypted_content"], max_output_tokens=self.configuration.max_output_tokens,
            )
        except Exception as exc:
            error_type = next((label for error, label in (
                (APITimeoutError, "timeout"), (RateLimitError, "rate_limit"),
                (AuthenticationError, "authentication"), (PermissionDeniedError, "permission"),
                (APIConnectionError, "connection"), (APIError, "api_error"),
            ) if isinstance(exc, error)), "unexpected_error")
            self._record(current, started, error_type=error_type)
            raise AgentError("Model request failed or timed out. No automatic retry was made.") from None
        self._record(current, started, response=response)
        if response.status != "completed":
            raise AgentError("Model response did not complete.")
        items = [item.model_dump(mode="json", exclude_none=True) for item in response.output]
        calls = []
        for item in items:
            if item.get("type") != "function_call":
                continue
            try:
                arguments = json.loads(item["arguments"])
                if not isinstance(arguments, dict):
                    raise ValueError
                calls.append(ToolCall(item["name"], arguments, item["call_id"]))
            except (ValueError, KeyError, TypeError):
                raise AgentError("Model returned malformed tool arguments.") from None
        return ModelTurn(items, calls, response.output_text)

    def _record(self, current, started: int, *, response=None, error_type=None):
        duration_ms = (perf_counter_ns() - started) / 1_000_000
        raw_model = getattr(response, "model", None)
        reported_model = raw_model if isinstance(raw_model, str) and 0 < len(raw_model) <= 200 else None
        raw_status = getattr(response, "status", None)
        response_status = (raw_status if raw_status in {
            "completed", "incomplete", "failed", "cancelled", "queued", "in_progress",
        } else "unknown") if response is not None else None
        usage_status, usage = parse_usage(getattr(response, "usage", None))
        measurement = ModelRequestMeasurement(
            sequence=len(self.requests) + 1, requested_model=self.model, reported_model=reported_model,
            duration_ms=duration_ms, outcome="error" if error_type else "response",
            response_status=response_status, error_type=error_type, usage_status=usage_status, usage=usage,
        )
        self.requests.append(measurement)
        current.set_attribute("agent.request_duration_ms", duration_ms)
        current.set_attribute("agent.usage_status", usage_status)
        if reported_model:
            current.set_attribute(SpanAttributes.LLM_MODEL_NAME, reported_model)
        if response_status:
            current.set_attribute("agent.response_status", response_status)
        if error_type:
            current.set_attribute("agent.provider_error", error_type)
        if usage is not None:
            for attribute, value in (
                (SpanAttributes.LLM_TOKEN_COUNT_PROMPT, usage.input_tokens),
                (SpanAttributes.LLM_TOKEN_COUNT_COMPLETION, usage.output_tokens),
                (SpanAttributes.LLM_TOKEN_COUNT_TOTAL, usage.total_tokens),
                (SpanAttributes.LLM_TOKEN_COUNT_PROMPT_DETAILS_CACHE_READ, usage.cached_input_tokens),
                (SpanAttributes.LLM_TOKEN_COUNT_PROMPT_DETAILS_CACHE_WRITE, usage.cache_write_input_tokens),
                (SpanAttributes.LLM_TOKEN_COUNT_COMPLETION_DETAILS_REASONING, usage.reasoning_output_tokens),
            ):
                if value is not None:
                    current.set_attribute(attribute, value)

    def close(self):
        self.client.close()


def make_driver(mode: str):
    if mode == "demo":
        return DemoDriver(), None
    if mode == "demo_claim_only":
        return ClaimOnlyDemoDriver(), None
    if mode == "demo_reconcile":
        return ReconcileDemoDriver(), None
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("OPENAI_MODEL", "").strip()
    if not key or not model:
        raise ProviderNotConfigured("OpenAI mode requires OPENAI_API_KEY and OPENAI_MODEL on the backend.")
    return OpenAIDriver(key, model), model
