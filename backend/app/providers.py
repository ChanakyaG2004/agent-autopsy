import json
import os

from openai import APIError, OpenAI

from app.agent import AgentError, DemoDriver, INSTRUCTIONS, ModelTurn, ToolCall
from app.tools import TOOL_SCHEMAS


class ProviderNotConfigured(Exception):
    pass


class OpenAIDriver:
    def __init__(self, api_key: str, model: str):
        self.model = model
        self.client = OpenAI(api_key=api_key, timeout=10.0, max_retries=0)

    def decide(self, history: list[dict]) -> ModelTurn:
        try:
            response = self.client.responses.create(
                model=self.model, instructions=INSTRUCTIONS, input=history,
                tools=TOOL_SCHEMAS, parallel_tool_calls=False, store=False,
                include=["reasoning.encrypted_content"], max_output_tokens=1024,
            )
        except APIError:
            raise AgentError("Model request failed or timed out. No automatic retry was made.") from None
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

    def close(self):
        self.client.close()


def make_driver(mode: str):
    if mode == "demo":
        return DemoDriver(), None
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("OPENAI_MODEL", "").strip()
    if not key or not model:
        raise ProviderNotConfigured("OpenAI mode requires OPENAI_API_KEY and OPENAI_MODEL on the backend.")
    return OpenAIDriver(key, model), model
