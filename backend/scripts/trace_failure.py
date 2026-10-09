"""Emit a clearly tagged rejected-tool diagnostic, without writing experiment data."""

from app.agent import ModelTurn, ToolCall, execute_agent
from app.telemetry import configure_tracing, mark_failure, shutdown_tracing, span, trace_id


class RejectedToolDriver:
    def decide(self, history):
        return ModelTurn([], [ToolCall("unregistered-tool", {}, "diagnostic-call")])


def main():
    provider = configure_tracing()
    if provider is None:
        raise SystemExit("Set AGENT_AUTOPSY_TRACING_ENABLED=true to emit this diagnostic.")
    try:
        with span("diagnostic.rejected_tool", "AGENT", **{
            "agent.mode": "demo", "agent.diagnostic": True,
        }) as root:
            result = execute_agent(RejectedToolDriver())
            root.set_attribute("agent.execution_status", result.status)
            if result.error:
                mark_failure(root, result.error)
            print(f"Diagnostic execution: {result.status}")
            print(f"Trace ID: {trace_id(root)}")
            print("No experiment or run record was created. Inspect the rejected TOOL span in Phoenix.")
    finally:
        shutdown_tracing(provider)


if __name__ == "__main__":
    main()
