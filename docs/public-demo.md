# Public recorded demo

The public website is an interactive, static evidence explorer. Visitors can switch between three scenarios and three policies, compare saved outcomes, inspect each recorded tool step, read all four evaluator checks, and download the snapshot. It requires no account, local service, database, or model API key.

The controls do not perform new inference, enqueue jobs, or simulate an active cloud worker. The displayed observations come from the actual Python scripted agent loop, sandbox, deterministic evaluators, benchmark summarizer, and read-only comparison implementation. No private database records or model histories are exported. Snapshot UUIDs identify exported records; they are not hosted database receipts. No live Phoenix trace links are invented.

## Regenerate the evidence

From `backend/`, using the locked development environment:

```bash
uv run --locked --env-file .env python scripts/export_demo.py
```

The script writes `frontend/public/demo-evidence.json`. It records real execution timestamps, the engine source commit and file hashes, all nine complete RunRead observations, the fixed suite definition, the real benchmark summary, and three compatible baseline/reconciliation comparison reports. It makes no provider or database calls. Source engine imports require the normal backend configuration, but no running database is needed.

The snapshot is versioned in Git. Refresh it deliberately after changing the engine or its evaluators; normal frontend builds do not run Python or replace evidence silently.

## Build and publish

The normal frontend still uses standalone output and the local API. `/demo` previews the recorded experience in that application. The public build replaces `/`, `/compare`, and `/demo` with the recorded experience:

```bash
cd frontend
AGENT_AUTOPSY_PUBLIC_DEMO=true npm run build
python3 -m http.server 4175 --directory out
```

`frontend/vercel.json` sets the public build command. Deploy `frontend/` as the Vercel project root. Static export serves HTML, CSS, JSON, and client-side interactions without persistent services or inference. The normal Compose/local build is unchanged. Account plan limits still apply; this configuration provisions no paid database, worker, or model service.

Verify the production URL without a session: the home page and `/compare` must load, and `/demo-evidence.json` must return all nine observations. Test scenario and policy switching, the claim-only negative control, evidence step navigation, keyboard access, and a narrow viewport. The public page must not request the localhost API or Phoenix collector.
