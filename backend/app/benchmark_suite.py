"""The first immutable suite: one task, three scenarios, three scripted drivers."""

import hashlib
import json
import platform
import subprocess
from copy import deepcopy
from importlib.metadata import version
from pathlib import Path

from app.agent import INSTRUCTIONS, MAX_TURNS, TASK
from app.assurance import ANSWER_INSTRUCTIONS
from app.tools import TOOL_SCHEMAS

SUITE_VERSION = "refund-resilience-v1"
MODES = ("demo", "demo_reconcile", "demo_claim_only")
CASES = (
    ("full-refund-normal", "normal"),
    ("full-refund-lost-response", "timeout_after_commit"),
    ("full-refund-permission-denied", "permission_denied"),
)


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def suite_definition() -> dict:
    return {
        "suite_version": SUITE_VERSION,
        "description": "One fixed refund task across three scenarios; scripted drivers only.",
        "distinct_tasks": 1,
        "agent_version": "refund-v1",
        "task": TASK,
        "cases": [{"case_key": key, "scenario": scenario} for key, scenario in CASES],
        "drivers": list(MODES),
        "max_repetitions": 3,
    }


def build_manifest(repetitions: int, schema_revision: str) -> dict:
    backend = Path(__file__).resolve().parents[1]
    suite = suite_definition()
    files = sorted((backend / "app").glob("*.py")) + [backend / "pyproject.toml", backend / "uv.lock"]
    fingerprints = {str(path.relative_to(backend)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in files}
    revision, dirty = None, None
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=backend,
                                           timeout=2, stderr=subprocess.DEVNULL, text=True).strip()
        dirty = bool(subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=normal", "--", "app", "pyproject.toml", "uv.lock"],
            cwd=backend, timeout=2, stderr=subprocess.DEVNULL, text=True,
        ).strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return {
        "manifest_version": "benchmark-manifest-v1",
        "suite": suite,
        "suite_digest": digest(suite),
        "repetitions": repetitions,
        "schedule": [{"position": position, "case_key": case_key, "scenario": scenario,
                      "mode": mode, "repetition": repetition}
                     for position, (case_key, scenario, mode, repetition) in enumerate(
                         (key, scenario, mode, repetition)
                         for key, scenario in CASES for mode in MODES
                         for repetition in range(1, repetitions + 1))],
        "configuration": {
            "instructions": INSTRUCTIONS, "instructions_digest": digest(INSTRUCTIONS),
            "tool_schemas": deepcopy(TOOL_SCHEMAS), "tool_schemas_digest": digest(TOOL_SCHEMAS),
            "max_turns": MAX_TURNS,
            "ledger_evaluator": "refund-ledger-v1", "recovery_evaluator": "recovery-policy-v1",
            "security_evaluator": "tool-policy-v2", "grounding_evaluator": "refund-grounding-v1",
            "answer_contract": "refund-answer-v1",
            "report_instructions": ANSWER_INSTRUCTIONS, "report_instructions_digest": digest(ANSWER_INSTRUCTIONS),
            "model": None, "randomness": "None; deterministic scripts and fixed schedule.",
        },
        "source": {"git_revision": revision, "backend_dirty": dirty,
                   "files": fingerprints, "source_digest": digest(fingerprints)},
        "environment": {"python": platform.python_version(), "system": platform.system(),
                        "machine": platform.machine(), "schema_revision": schema_revision,
                        "packages": {name: version(name) for name in
                                     ("fastapi", "pydantic", "sqlalchemy", "openai", "opentelemetry-sdk")}},
    }
