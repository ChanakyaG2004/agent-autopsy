"""A bounded tool loop, independent of HTTP, persistence, and model vendors."""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.tools import RefundSandbox, ToolError

TASK = "Refund the full paid amount for order-123, then report what happened."
INSTRUCTIONS = (
    "You are a refund agent operating only on simulated orders. Read the order before "
    "refunding. Use tools for actions, and report only results supported by tool output. "
    "Call at most one tool at a time. Amounts are integer USD cents."
)
MAX_TURNS = 6


class AgentError(Exception):
    """A safe, public error message; never include raw provider errors."""


@dataclass
class ToolCall:
    name: str
    arguments: dict
    call_id: str


@dataclass
class ModelTurn:
    output_items: list[dict]
    calls: list[ToolCall] = field(default_factory=list)
    answer: str = ""


class Driver(Protocol):
    def decide(self, history: list[dict]) -> ModelTurn: ...


@dataclass
class RunResult:
    status: str
    output: str | None
    error: str | None
    steps: list[dict]
    initial_state: dict
    final_state: dict


def execute_agent(driver: Driver) -> RunResult:
    sandbox = RefundSandbox()
    initial = sandbox.snapshot()
    history: list[dict[str, Any]] = [{"role": "user", "content": TASK}]
    steps: list[dict] = []
    output = None
    error = None
    try:
        for turn_number in range(1, MAX_TURNS + 1):
            turn = driver.decide(history)
            history.extend(turn.output_items)
            if len(turn.calls) > 1:
                raise AgentError("Model returned multiple tool calls; execution refused.")
            if turn.calls:
                call = turn.calls[0]
                step = {"turn": turn_number, "kind": "tool", "tool": call.name,
                        "arguments": call.arguments}
                steps.append(step)
                try:
                    result = sandbox.execute(call.name, call.arguments)
                except ToolError as exc:
                    step["error"] = str(exc)
                    raise AgentError(str(exc)) from None
                step["result"] = result
                history.append({"type": "function_call_output", "call_id": call.call_id,
                                "output": json.dumps(result)})
            elif turn.answer.strip():
                output = turn.answer
                steps.append({"turn": turn_number, "kind": "answer", "text": output})
                break
            else:
                raise AgentError("Model returned neither a tool call nor a final answer.")
        else:
            raise AgentError(f"Execution stopped at the {MAX_TURNS}-turn limit.")
    except AgentError as exc:
        error = str(exc)
    except Exception as exc:
        logging.getLogger(__name__).error("Unexpected runner failure: %s", type(exc).__name__)
        error = "Unexpected execution failure. Inspect the saved steps before retrying."
    return RunResult("failed" if error else "completed", output, error, steps,
                     initial, sandbox.snapshot())


class DemoDriver:
    """A deterministic script that exercises the real loop; not an LLM."""

    def decide(self, history: list[dict]) -> ModelTurn:
        results = [json.loads(item["output"]) for item in history
                   if item.get("type") == "function_call_output"]
        if len(results) >= 2:
            state = results[-1]
            return ModelTurn([], answer=(
                f"The simulated order {state['order_id']} now has "
                f"{state['refunded_cents']} USD cents refunded."
            ))
        name = "get_order" if not results else "issue_refund"
        arguments = {"order_id": "order-123"}
        if results:
            arguments["amount_cents"] = results[-1]["paid_cents"] - results[-1]["refunded_cents"]
        call_id = f"demo-call-{len(results) + 1}"
        item = {"type": "function_call", "name": name, "call_id": call_id,
                "arguments": json.dumps(arguments)}
        return ModelTurn([item], [ToolCall(name, arguments, call_id)])
