# Experiment configuration validation

This slice connects the browser to FastAPI. It validates a proposed configuration without saving data, checking that an agent exists, or executing a scenario.

## Request flow

```text
Server-rendered page
  → interactive ExperimentForm in the browser
  → POST http://127.0.0.1:8000/experiments/validate
  → Pydantic validation
  → confirmation or HTTP 422
  → success or error message in the form
```

The browser makes the API call directly. There is no Next.js API proxy or database involved.

## Contract

```json
{
  "name": "Refund recovery baseline",
  "agent_version": "refund-v1",
  "scenarios": ["normal", "timeout_after_commit"]
}
```

Names must have 3–80 characters after trimming; agent-version labels need 1–80. The list must contain 1–3 unique scenario keys from `normal`, `timeout_after_commit`, and `permission_denied`. Unknown fields are rejected. These are planned scenario identifiers, not implemented agents or faults.

Valid requests return HTTP 200 and a `message`. Invalid requests return HTTP 422 with FastAPI's structured `detail` errors. The frontend currently shows a summary of the constraints for 422 responses; field-specific server error rendering can be added later.

## Concepts introduced

- **Typed props:** `EvidenceItemProps` defines the title and description accepted by a reusable evidence list item. Props supply data to a component.
- **State:** `useState` retains field values and submission state between renders. Updating state makes React render the new UI.
- **Server/client boundary:** the page and evidence items remain Server Components. Only the interactive form uses `"use client"` for state and event handlers.
- **Event handling:** `onSubmit` prevents normal browser navigation, serializes the draft, and sends JSON with `fetch`.
- **Loading and errors:** submission disables the controls and displays progress. Validation failures, unexpected responses, server errors, network failures, and a 10-second timeout produce feedback. Editing a field clears stale feedback.
- **Runtime validation:** TypeScript checks the frontend during development; it does not validate incoming HTTP requests. Pydantic validates the actual payload before the route runs. The browser also checks the shape of the success response rather than trusting a type assertion.
- **CORS:** frontend port 3000 and backend port 8000 are different origins. The API allows browser requests from the two local frontend addresses. CORS is a browser access policy, not authentication or tool authorization.

The frontend API URL defaults to `http://127.0.0.1:8000`. To change it, copy `frontend/.env.example` to `frontend/.env.local`, edit it, and restart the frontend. `NEXT_PUBLIC_` variables are exposed to the browser; never put secrets in them.

## Next boundary

A successful response establishes that the configuration matches this contract. It does not establish that the agent exists or that its execution is correct. The next persistence slice will introduce an experiment record, database model, migration, and creation endpoint.
