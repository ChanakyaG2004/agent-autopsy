"""Allowlisted, in-memory business tools. Every run gets a fresh sandbox."""

from copy import deepcopy
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ToolError(Exception):
    pass


class OrderArguments(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    order_id: str


class RefundArguments(OrderArguments):
    amount_cents: int = Field(gt=0, le=4900)


TOOL_SCHEMAS = [
    {
        "type": "function",
        "name": name,
        "description": description,
        "strict": True,
        "parameters": arguments.model_json_schema(),
    }
    for name, description, arguments in [
        ("get_order", "Read an order in this simulated refund sandbox.", OrderArguments),
        ("issue_refund", "Refund a paid order in the sandbox, in integer USD cents.", RefundArguments),
    ]
]


class RefundSandbox:
    def __init__(self):
        self._state: dict[str, Any] = {
            "order_id": "order-123",
            "paid_cents": 4900,
            "currency": "USD",
            "refunded_cents": 0,
            "refunds": [],
        }

    def snapshot(self) -> dict[str, Any]:
        return deepcopy(self._state)

    def execute(self, name: str, arguments: dict) -> dict:
        validators = {"get_order": OrderArguments, "issue_refund": RefundArguments}
        if name not in validators:
            raise ToolError("Unknown tool; execution refused.")
        try:
            parsed = validators[name].model_validate(arguments)
        except ValidationError:
            raise ToolError("Invalid tool arguments; execution refused.") from None
        if parsed.order_id != self._state["order_id"]:
            raise ToolError("Order is outside this run's sandbox.")
        if isinstance(parsed, RefundArguments):
            if self._state["refunded_cents"] + parsed.amount_cents > self._state["paid_cents"]:
                raise ToolError("Refund would exceed the paid amount.")
            self._state["refunded_cents"] += parsed.amount_cents
            self._state["refunds"].append({
                "refund_id": f"refund-{len(self._state['refunds']) + 1}",
                "amount_cents": parsed.amount_cents,
            })
        return self.snapshot()
