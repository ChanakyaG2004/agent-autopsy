"""Release acceptance over HTTP. Creates saved demo evidence; never deletes history.

Requires a migrated API and a running separate worker. Optional --model runs
three local Ollama observations; it never selects a paid provider.
"""

import argparse
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4


class SmokeFailure(Exception):
    pass


class API:
    def __init__(self, origin, timeout):
        parsed = urlsplit(origin)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            raise SmokeFailure("Use a local HTTP API origin.")
        self.origin, self.timeout = origin.rstrip("/"), timeout
        self.opener = build_opener(ProxyHandler({}))

    def request(self, path, body=None, expected=200):
        request = Request(self.origin + path, data=None if body is None else json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=10) as response:
                require(response.status == expected, f"Unexpected HTTP status for {path}")
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, ValueError):
            raise SmokeFailure(f"HTTP check failed for {path}. Check API readiness and logs.") from None

    def submit(self, path, body):
        body = {**body, "request_id": str(uuid4())}
        job = self.request(path, body, 202)
        require(self.request(path, body, 202)["id"] == job["id"], "Request identity changed on retry")
        deadline = time.monotonic() + self.timeout
        while job["status"] in {"queued", "running"} and time.monotonic() < deadline:
            time.sleep(0.3)
            job = self.request(f'/jobs/{job["id"]}')
        require(job["status"] == "succeeded", f'Job {job["id"]} is {job["status"]}; check the separate worker')
        return job


def require(condition, message):
    if not condition:
        raise SmokeFailure(message)


def scripted(api):
    job = api.submit("/benchmark-jobs", {"repetitions": 1})
    report = api.request(f'/benchmarks/{job["benchmark_id"]}')
    counts = report["summary"]["overall"]
    expected = {"planned": 9, "recorded": 9, "pending": 0, "infrastructure_failed": 0,
                "execution_completed": 7, "execution_failed": 2, "ledger_passed": 4, "ledger_failed": 5}
    require(report["status"] == "completed" and all(counts[k] == v for k, v in expected.items()),
            "Scripted regression counts changed")
    runs = {(item["mode"], item["run"]["scenario"]): item["run"] for item in report["items"]}
    baseline, recovered = runs["demo", "timeout_after_commit"], runs["demo_reconcile", "timeout_after_commit"]
    require(baseline["evaluation"]["verdict"] == recovered["evaluation"]["verdict"] == "passed",
            "Both timeout ledgers should be correct")
    require(baseline["recovery_evaluation"]["verdict"] == "failed" and recovered["recovery_evaluation"]["verdict"] == "passed",
            "Recovery policy did not distinguish reconciliation")
    for scenario in ("normal", "timeout_after_commit", "permission_denied"):
        control = runs["demo_claim_only", scenario]
        require(control["status"] == "completed" and control["evaluation"]["verdict"] == "failed",
                "The negative control must complete while failing the business goal")
    comparison = api.request("/run-comparisons?" + urlencode({"baseline_id": baseline["id"], "candidate_id": recovered["id"]}))
    require(comparison["outcomes_comparable"] and comparison["recovery_comparable"], "Saved comparison is unavailable")
    require(api.request(f'/benchmarks/{report["id"]}') == report, "Reading evidence changed it")
    return {"job_id": job["id"], "benchmark_id": report["id"], "counts": expected,
            "sample_trace_id": recovered["trace_id"]}


def model_observations(api):
    observations = []
    for scenario in ("normal", "timeout_after_commit", "permission_denied"):
        experiment = api.request("/experiments", {"name": f"Release validation {scenario}",
                                 "agent_version": "refund-v1", "scenarios": [scenario]}, 201)
        job = api.submit(f'/experiments/{experiment["id"]}/jobs', {"mode": "ollama"})
        run = next(r for r in api.request(f'/experiments/{experiment["id"]}/runs') if r["id"] == job["run_id"])
        expected_ledger = "failed" if scenario == "permission_denied" else "passed"
        expected_recovery = "not_applicable" if scenario == "normal" else "passed"
        require(run["status"] == "completed" and run["evaluation"]["verdict"] == expected_ledger
                and run["recovery_evaluation"]["verdict"] == expected_recovery
                and run["security_evaluation"]["verdict"] == run["grounding_evaluation"]["verdict"] == "passed",
                f"Local model observation did not meet acceptance criteria: {run['id']}")
        require(scenario == "normal" or run["fault_injected"], "Selected model fault was not exercised")
        observations.append({"scenario": scenario, "run_id": run["id"], "trace_id": run["trace_id"]})
    return observations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=int, default=120, help="Maximum seconds per job")
    parser.add_argument("--model", action="store_true", help="Also execute three local Ollama runs")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 1200:
        parser.error("Timeout must be 1–1200 seconds")
    try:
        api = API(args.api_url, args.timeout)
        require(api.request("/health/ready")["status"] == "ready", "API is not ready")
        result = {"passed": True, "scripted": scripted(api)}
        if args.model:
            result["local_model_observations"] = model_observations(api)
        print(json.dumps(result, indent=2))
        return 0
    except (SmokeFailure, KeyError, TypeError, StopIteration) as error:
        print(json.dumps({"passed": False, "detail": str(error) if isinstance(error, SmokeFailure) else "Incompatible response contract"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
