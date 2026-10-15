"""Native Ollama tool calling, restricted to installed models on a local server."""

import json
import os
from copy import deepcopy
from time import perf_counter_ns
from urllib.parse import urlsplit

import requests
from pydantic import ValidationError

from app.agent import AgentError, INSTRUCTIONS, MAX_TURNS, ModelTurn, ToolCall
from app.model_telemetry import (ModelRequestConfiguration, ModelRequestMeasurement,
                                 TokenUsage, fingerprint, summarize_requests)
from app.telemetry import span
from app.tools import TOOL_SCHEMAS

DEFAULT_MODEL = "llama3.1:latest"
DEFAULT_URL = "http://127.0.0.1:11434"
LOCAL_TOOL_INSTRUCTIONS = (
    " The only tool names are get_order and issue_refund. "
    "Use native tool calls for these actions, never JSON or descriptions of calls in your final text. "
    "First call get_order. If the order still needs a refund and permission has not been denied, "
    "call issue_refund with the remaining paid amount. Do not finish after only reading an unrefunded order. "
    "After an unknown-outcome timeout, call get_order again before deciding whether another refund is needed. "
    "After a permission denial, stop calling refund tools and explain the refusal. "
    "Finish with a plain-language report grounded in the actual tool results."
)


class OllamaUnavailable(Exception):
    """Safe local configuration/service error, never a raw HTTP response."""


def local_endpoint(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"} or port == 0):
            raise ValueError
    except ValueError:
        raise OllamaUnavailable("OLLAMA_BASE_URL must be an HTTP loopback origin, such as http://127.0.0.1:11434.") from None
    return value.rstrip("/")


def settings() -> tuple[str, str]:
    model = os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL).strip()
    if not model or len(model) > 200 or ":cloud" in model.lower():
        raise OllamaUnavailable("Choose an installed local OLLAMA_MODEL; cloud models are not supported.")
    return model, local_endpoint(os.environ.get("OLLAMA_BASE_URL", DEFAULT_URL).strip())


def parse_ollama_usage(data: dict):
    if data.get("prompt_eval_count") is None and data.get("eval_count") is None:
        return "unavailable", None
    try:
        inputs, outputs = data.get("prompt_eval_count"), data.get("eval_count")
        if type(inputs) is not int or type(outputs) is not int:
            return "invalid", None
        return "reported", TokenUsage(input_tokens=inputs, output_tokens=outputs,
                                       total_tokens=inputs + outputs,
                                       cached_input_tokens=data.get("prompt_eval_cached_count"))
    except ValidationError:
        return "invalid", None


class OllamaDriver:
    def __init__(self, model: str, base_url: str):
        self.model, self.base_url = model, local_endpoint(base_url)
        if not model or len(model) > 200 or ":cloud" in model.lower():
            raise OllamaUnavailable("Choose an installed local OLLAMA_MODEL; cloud models are not supported.")
        self.client = requests.Session()
        self.client.trust_env = False  # Do not send local requests through proxies or netrc authentication.
        self.requests: list[ModelRequestMeasurement] = []
        self.instructions = INSTRUCTIONS + LOCAL_TOOL_INSTRUCTIONS
        self.tools = [{"type": "function", "function": {
            "name": tool["name"], "description": tool["description"],
            "parameters": deepcopy(tool["parameters"]),
        }} for tool in TOOL_SCHEMAS]
        try:
            version = self._metadata("get", "/api/version")
            tags = self._metadata("get", "/api/tags")
            entries = tags.get("models")
            if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
                raise OllamaUnavailable("Ollama returned incompatible model metadata.")
            installed = next((entry for entry in entries if entry.get("name") == model), None)
            if installed is None:
                raise OllamaUnavailable("OLLAMA_MODEL is not installed locally. Select an installed tool-capable model.")
            info = self._metadata("post", "/api/show", {"model": model})
            if info.get("remote_model") or info.get("remote_host") or installed.get("remote_model") or installed.get("remote_host"):
                raise OllamaUnavailable("Cloud-backed Ollama models are refused; select a model with local weights.")
            if not isinstance(info.get("capabilities"), list) or "tools" not in info["capabilities"]:
                raise OllamaUnavailable("The selected local model does not advertise tool-calling support.")
            digest, server_version = installed.get("digest"), version.get("version")
            if not isinstance(digest, str) or not isinstance(server_version, str):
                raise OllamaUnavailable("Ollama model identity metadata is unavailable.")
            self.configuration = ModelRequestConfiguration(
                instructions_sha256=fingerprint(self.instructions), tool_schemas_sha256=fingerprint(self.tools),
                max_output_tokens=1024, max_turns=MAX_TURNS, timeout_seconds=60.0, max_retries=0,
                store=None, parallel_tool_calls=None, model_digest=digest, server_version=server_version,
                context_window_tokens=8192, temperature=0.0,
            )
        except Exception:
            self.client.close()
            raise

    def _metadata(self, method: str, path: str, body=None) -> dict:
        try:
            response = self.client.request(method, self.base_url + path, json=body,
                                           timeout=(3, 5), allow_redirects=False)
            if response.status_code != 200:
                raise OllamaUnavailable("Local Ollama metadata request failed. Check the service and installed model.")
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (requests.RequestException, ValueError):
            raise OllamaUnavailable("Cannot read the local Ollama service. Start Ollama and check its model installation.") from None

    @property
    def model_telemetry(self):
        return summarize_requests(self.model, self.requests, self.configuration, provider="ollama")

    def _messages(self, history: list[dict]) -> list[dict]:
        messages = [{"role": "system", "content": self.instructions}]
        names = {}
        for item in history:
            if item.get("role") == "user":
                messages.append({"role": "user", "content": item["content"]})
            elif item.get("type") == "ollama_message":
                messages.append(item["message"])
                for call_id, call in zip(item["call_ids"], item["message"].get("tool_calls", []), strict=True):
                    names[call_id] = call["function"]["name"]
            elif item.get("type") == "function_call_output":
                name = names.get(item["call_id"])
                if name is None:
                    raise AgentError("Local tool feedback has no matching call; execution refused.")
                messages.append({"role": "tool", "tool_name": name, "content": item["output"]})
        return messages

    def decide(self, history: list[dict]) -> ModelTurn:
        with span("ollama.chat", "LLM", **{"llm.system": "ollama", "llm.provider": "ollama",
                  "llm.model_name": self.model, "agent.requested_model": self.model}) as current:
            messages = self._messages(history)
            started = perf_counter_ns()
            try:
                response = self.client.post(self.base_url + "/api/chat", json={
                    "model": self.model, "messages": messages, "tools": self.tools, "stream": False,
                    "options": {"num_predict": self.configuration.max_output_tokens,
                                "num_ctx": self.configuration.context_window_tokens,
                                "temperature": self.configuration.temperature},
                }, timeout=(3, self.configuration.timeout_seconds), allow_redirects=False)
                if response.status_code != 200:
                    self._record(current, started, error="api_error")
                    raise AgentError("Local model request failed. No automatic retry was made.")
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError
            except (requests.RequestException, ValueError) as exc:
                category = "timeout" if isinstance(exc, requests.Timeout) else "connection" if isinstance(exc, requests.ConnectionError) else "unexpected_error"
                self._record(current, started, error=category)
                raise AgentError("Local model request failed or timed out. No automatic retry was made.") from None
            self._record(current, started, data=data)
            if data.get("done") is not True or data.get("done_reason") != "stop":
                raise AgentError("Local model response did not complete. No tool calls were executed.")
            message = data.get("message")
            if not isinstance(message, dict) or message.get("role") != "assistant" or not isinstance(message.get("content", ""), str):
                raise AgentError("Local model returned an invalid assistant message.")
            raw_calls = message.get("tool_calls") or []
            if not isinstance(raw_calls, list):
                raise AgentError("Local model returned malformed tool calls.")
            calls, clean_calls = [], []
            for index, raw in enumerate(raw_calls):
                function = raw.get("function") if isinstance(raw, dict) else None
                if not isinstance(function, dict) or not isinstance(function.get("name"), str) or not isinstance(function.get("arguments"), dict):
                    raise AgentError("Local model returned malformed tool arguments.")
                call_id = f"ollama-call-{len(self.requests)}-{index}"
                calls.append(ToolCall(function["name"], function["arguments"], call_id))
                clean_calls.append({"type": "function", "function": {
                    "name": function["name"], "arguments": function["arguments"],
                }})
            clean_message = {"role": "assistant", "content": message.get("content", "")}
            if clean_calls:
                clean_message["tool_calls"] = clean_calls
            return ModelTurn([{"type": "ollama_message", "message": clean_message,
                               "call_ids": [call.call_id for call in calls]}], calls, clean_message["content"])

    def _record(self, current, started: int, *, data=None, error=None):
        usage_status, usage = parse_ollama_usage(data or {})
        reported = data.get("model") if data else None
        reported = reported if isinstance(reported, str) and 0 < len(reported) <= 200 else None
        status = ("completed" if data.get("done") is True and data.get("done_reason") == "stop" else "incomplete") if data else None
        measurement = ModelRequestMeasurement(
            sequence=len(self.requests) + 1, requested_model=self.model, reported_model=reported,
            duration_ms=(perf_counter_ns() - started) / 1_000_000,
            outcome="error" if error else "response", response_status=status, error_type=error,
            usage_status=usage_status, usage=usage,
        )
        self.requests.append(measurement)
        current.set_attribute("agent.request_duration_ms", measurement.duration_ms)
        current.set_attribute("agent.usage_status", usage_status)
        if reported:
            current.set_attribute("llm.model_name", reported)
        if status:
            current.set_attribute("agent.response_status", status)
        if error:
            current.set_attribute("agent.provider_error", error)
        if usage:
            for key, value in (("llm.token_count.prompt", usage.input_tokens),
                               ("llm.token_count.completion", usage.output_tokens),
                               ("llm.token_count.total", usage.total_tokens),
                               ("llm.token_count.prompt_details.cache_read", usage.cached_input_tokens)):
                if value is not None:
                    current.set_attribute(key, value)

    def close(self):
        self.client.close()
