# Recorded demo

The former public website was removed on October 27, 2026. Its screenshots remain in [`images/`](images/), and the recorded explorer remains available for local preview. It is an interactive, static evidence explorer: switch between three scenarios and three policies, compare saved outcomes, inspect each recorded tool step, read all four evaluator checks, and download the snapshot. The built export requires no database or model API key.

The controls do not perform new inference, enqueue jobs, or simulate an active cloud worker. The displayed observations come from the actual Python scripted agent loop, sandbox, deterministic evaluators, benchmark summarizer, and read-only comparison implementation. No private database records or model histories are exported. Snapshot UUIDs identify exported records; they are not hosted database receipts. No live Phoenix trace links are invented.

## Regenerate the evidence

From `backend/`, using the locked development environment:

```bash
uv run --locked --env-file .env python scripts/export_demo.py
```

The script writes `frontend/public/demo-evidence.json`. It records real execution timestamps, the engine source commit and file hashes, all nine complete RunRead observations, the fixed suite definition, the real benchmark summary, and three compatible baseline/reconciliation comparison reports. It makes no provider or database calls. Source engine imports require the normal backend configuration, but no running database is needed.

The snapshot is versioned in Git. Refresh it deliberately after changing the engine or its evaluators; normal frontend builds do not run Python or replace evidence silently.

## Build and preview

The normal frontend still uses standalone output and the local API. `/demo` previews the recorded experience in that application. The static build replaces `/`, `/compare`, and `/demo` with the recorded experience:

```bash
cd frontend
AGENT_AUTOPSY_PUBLIC_DEMO=true npm run build
python3 -m http.server 4175 --directory out
```

Open `http://127.0.0.1:4175` to use the local preview. Static export serves HTML, CSS, JSON, and client-side interactions without persistent backend services or inference. The normal Compose/local build is unchanged. `frontend/vercel.json` retains the optional static-build command, but the Vercel project and its deployments have been deleted.

To verify a local static build, load the home page and `/compare`, and check that `/demo-evidence.json` returns all nine observations. Test scenario and policy switching, the claim-only negative control, evidence step navigation, keyboard access, and a narrow viewport. The recorded explorer must not request the localhost API or Phoenix collector.
