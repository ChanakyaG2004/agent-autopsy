import hashlib
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import TASK, DemoDriver, ReconcileDemoDriver, ClaimOnlyDemoDriver, execute_agent
from app.assurance import evaluate_grounding, evaluate_security
from app.benchmark import summarize
from app.benchmark_suite import CASES, MODES, suite_definition
from app.comparisons import ComparisonSide, compare_sides
from app.evaluation import evaluate_refund
from app.recovery import evaluate_recovery
from app.schemas import RunRead


def export():
    root = Path(__file__).resolve().parents[2]
    drivers = dict(zip(MODES, [DemoDriver, ReconcileDemoDriver, ClaimOnlyDemoDriver]))
    runs, rows, schedule = [], [], []
    for case_key, scenario in CASES:
        for mode in MODES:
            started = datetime.now(timezone.utc)
            result = execute_agent(drivers[mode](), scenario)
            evidence = dict(scenario=scenario, steps=result.steps,
                            initial_state=result.initial_state, final_state=result.final_state)
            run = RunRead(
                id=uuid4(), experiment_id=uuid4(), mode=mode, scenario=scenario,
                model_name=None, trace_id=None, model_telemetry=None, task=TASK,
                evaluation=evaluate_refund(result.final_state),
                recovery_evaluation=evaluate_recovery(fault_injected=result.fault_injected, **evidence),
                security_evaluation=evaluate_security(**evidence),
                grounding_evaluation=evaluate_grounding(output=result.output, steps=result.steps),
                started_at=started, finished_at=datetime.now(timezone.utc), **asdict(result),
            )
            runs.append(run)
            position = len(schedule)
            schedule.append(dict(position=position, case_key=case_key, scenario=scenario, mode=mode))
            rows.append((SimpleNamespace(position=position, status='completed'), SimpleNamespace(
                status=run.status, fault_injected=run.fault_injected,
                evaluation=run.evaluation.model_dump(),
                recovery_evaluation=run.recovery_evaluation.model_dump(),
            )))
    summary = summarize(dict(schedule=schedule), rows)
    assert summary.overall.planned == summary.overall.recorded == 9
    assert summary.overall.ledger_passed == 4 and summary.overall.recovery_passed == 2
    comparisons = []
    for _, scenario in CASES:
        sides = {r.mode: ComparisonSide(experiment_name=f'Recorded {scenario}', agent_version='refund-v1', run=r)
                 for r in runs if r.scenario == scenario}
        comparisons.append(compare_sides(sides['demo'], sides['demo_reconcile']).model_dump(mode='json'))
    files = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted((root / 'backend/app').glob('*.py'))}
    data = dict(
        snapshot_version='recorded-demo-v1', recorded_at=datetime.now(timezone.utc).isoformat(),
        source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
        source_files=files, suite=suite_definition(), summary=summary.model_dump(mode='json'),
        execution='Actual in-process scripted agent loop and deterministic evaluators. No model inference, database jobs, or Phoenix export.',
        identifiers='UUIDs identify records in this exported snapshot; they are not hosted database job receipts.',
        runs=[run.model_dump(mode='json') for run in runs], comparisons=comparisons,
    )
    destination = root / 'frontend/public/demo-evidence.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(data, indent=2) + '\n')
    print(f'Exported {len(runs)} real scripted observations to {destination.relative_to(root)}')


if __name__ == '__main__':
    export()
