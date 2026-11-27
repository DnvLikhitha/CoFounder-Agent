# Run contract v1

This directory is the proposed shared interface for Likhitha's FastAPI backend and Surya's standalone Vite + React + JavaScript frontend. The contract version is `1.0`, with REST paths under `/api/v1`. The schema-only application in `backend/contracts/rest.py` describes future handlers. Runtime integration belongs in the subsequent backend PR. The current application continues to register its legacy routers.

## Consumer files

- `openapi.json` describes REST requests, responses, errors, query parameters, and downloads using OpenAPI 3.1.
- `sse.schema.json` describes each SSE `data` envelope using JSON Schema 2020-12 and a discriminated event union.
- `examples.json` contains start, history, artifact, review, and error payloads.
- `fixtures/succeeded/` and `fixtures/partial/` each contain an initial `snapshot.json`, ordered `events.jsonl`, wire-format `events.sse`, expected `final.json`, and artifact response bodies in `artifacts.json`.

JavaScript can load these JSON files directly. No generated TypeScript client is required. The two-step fixture manifests deliberately demonstrate a variable pipeline size. Each includes a review pause and approval. The partial fixture preserves completed research after summary generation fails.

## Existing interface inspected

| Legacy operation | Current behavior and caller | v1 replacement |
| --- | --- | --- |
| `POST /api/run` | `frontend/lib/api.ts` sends problem/domain/geography and receives run_id/started | `POST /api/v1/runs` |
| `GET /api/run/{run_id}` | Returns database row, outputs, and optional in-memory context | `GET /api/v1/runs/{run_id}` |
| `GET /api/run/{run_id}/stream` | `createEventSource` and the run page consume agent_start/done/error and pipeline_complete/error, without IDs | `GET /api/v1/runs/{run_id}/events` |
| `GET /api/runs` | History page reads id/problem_raw/status/timestamps, capped at 25 | `GET /api/v1/runs` |
| `GET /api/run/{run_id}/result` | Run page fetches flat results after stream failure. Both run.py and export.py declare this route. main.py registers run.py first | Snapshot artifact references and artifact reads |
| `GET /api/run/{run_id}/export/{format}` | getExportUrl supports pdf/markdown/pptx | `GET /api/v1/runs/{run_id}/exports/{format}` |
| `DELETE /api/run/{run_id}` | Legacy deletion route | Deferred from v1 MVP |

The existing orchestrator has 16 agents and can finish after individual agent failures and fallback output. A legacy `completed` value alone therefore cannot determine v1 success. The adapter must examine step outcomes and artifact quality. The current checked-in frontend is Next.js/TypeScript. Surya's new frontend can implement this interface independently.

## MVP endpoints

| Method and path | Response | Required UI use |
| --- | --- | --- |
| `POST /api/v1/runs` | 202 RunSnapshot, initially queued | Submit input and receive run ID, manifest, and replay cursor |
| `GET /api/v1/runs/{run_id}` | 200 RunSnapshot | Initial load, reload, and stream recovery |
| `GET /api/v1/runs/{run_id}/events?after=N` | 200 text/event-stream | Replay all events greater than N, then follow live events |
| `GET /api/v1/runs?limit=25&cursor=...` | 200 HistoryPage | History with opaque next_cursor |
| `GET /api/v1/runs/{run_id}/artifacts` | 200 ArtifactList | Refresh artifact references |
| `GET /api/v1/runs/{run_id}/artifacts/{artifact_id}` | 200 Artifact | Read output content |
| `POST /api/v1/runs/{run_id}/reviews/{review_id}/decisions` | 200 ReviewReceipt | Approve or reject a pending review |
| `GET /api/v1/runs/{run_id}/exports/{format}` | 200 attachment | Download pdf, markdown, or pptx |

Run input requires `problem` (10–500 characters). `domain` and `geography` are optional nullable strings, each at most 100 characters. Snapshot fields supply all information required for rendering progress, results, evaluations, and the active review. Fields without schema defaults must be present, including nullable timestamps and errors. Empty collections use `[]`. All timestamps include an offset, with UTC recommended. IDs are opaque to clients. Event IDs are integers within JavaScript's safe integer range.

History sorts by `(created_at DESC, run_id DESC)` with a stable keyset cursor. `next_cursor: null` means the last page. Invalid cursors return 422. MVP history uses the application's existing demo visibility scope. Authentication and tenant authorization require a subsequent explicit contract decision before multi-user production use.

Artifact bodies have `run_id`, `reference`, and JSON-compatible `content`. JSON content may be an object, array, or scalar, preserving existing output shapes. For text media types, content is a JSON string. Artifact `kind` maps to domain output names such as `market_research` and `executive_summary`. Render unknown kinds with a generic viewer. Artifact IDs and content are immutable after publication. A replacement artifact receives a new ID. References use API-relative hrefs, resolved against the backend origin.

## Status and manifest decisions

| Status | Run meaning | Step meaning |
| --- | --- | --- |
| queued | Accepted, awaiting execution | Awaiting dependencies or worker |
| running | Execution is active | Attempt is active |
| awaiting_review | Paused for one pending decision | Paused for a decision affecting this step |
| succeeded | All required work completed with complete outputs and accepted required checks | Complete output and accepted required checks |
| partial | Terminal with usable artifacts and at least one failed, degraded, or missing required output/check | Usable but incomplete or fallback output |
| failed | Terminal with no usable artifacts | Attempts exhausted with no usable output |
| skipped | Unavailable for runs | Execution omitted due to dependency failure or policy |

Run terminal states are succeeded, partial, and failed. Step terminal states additionally include skipped. Terminal runs emit no further events. Successful runs can omit optional steps. A failed optional step does not alone force a partial run. Required failure with usable output gives partial. Review rejection ends the run as partial if usable artifacts remain, otherwise failed, and marks remaining queued steps skipped. Approval resumes running. Retry attempts occur within running and increment `attempt`. Automatic retries of terminal runs and revision requests are deferred.

The server freezes a versioned manifest at run creation. Every step has a stable ID, display label, phase, display order, dependency IDs, required flag, and possible artifact kinds. Dependencies form an acyclic graph and reference existing steps. Snapshot `steps` contains exactly one state for every manifest entry. Array order is preserved by replay, while display sorting uses `order` then `step_id`. Clients derive counts and labels from the manifest. A changed pipeline produces a new manifest version for new runs.

An evaluation records its evaluator and version, target step/artifact, outcome, optional normalized score, reasons, and timestamp. `not_evaluated` is explicit when no evaluation was performed. `needs_review` can lead to a ReviewRequest. Evaluation policy determines which checks are required. The run status remains authoritative for clients. Raw provider errors, prompts, tokens, credentials, and database internals are excluded from the public error message.

Only one review is pending per run. `decision_id` is a client-generated UUID retained across retries. Reposting the same decision ID and payload to the same review returns the original receipt and creates no duplicate event. Reusing the ID with different content or deciding an already resolved review with a new ID returns 409. The server commits the decision, receipt, and corresponding event atomically. Approval clears pending_review and resumes the run. Reviews have no expiry in the MVP.

## Snapshot, replay, and reconnect

The backend must persist events and state together. Snapshot reads are consistent through `last_event_id`, including manifest, steps, artifacts, evaluations, and review state. Event IDs start at 1 and are contiguous and strictly increasing per run, including concurrent workers. Cursor 0 precedes the first event. Restarting workers must preserve the counter and event log.

1. Fetch a snapshot and initialize UI state. Save its `last_event_id` as the applied cursor.
2. For an active run, open EventSource at `/api/v1/runs/{run_id}/events?after={cursor}`. The server first replays persisted events with IDs strictly greater than the cursor and then follows new events without a replay/live gap.
3. Register listeners for all six names in the event union. Each frame has `id` equal to the decimal event_id, `event` equal to type, and `data` equal to the complete JSON envelope. Check run_id, contract_version, event type, and the equality of frame ID and payload event_id.
4. Ignore IDs less than or equal to the applied cursor. Apply the next event and advance the cursor together. An ID greater than cursor + 1 indicates a gap. Close the stream and obtain a fresh snapshot. Treat malformed or unknown events the same way and surface persistent version incompatibility.
5. Native EventSource reconnects send Last-Event-ID automatically. When supplied, this header takes precedence over `after`, including 0. On manual reconnect, use the last successfully applied cursor in `after`. Persisting a cursor requires persisting its matching state. On page reload, fetch a fresh snapshot.
6. Close EventSource once a terminal run.updated is applied. A terminal snapshot needs no stream. A stream opened at the end of a terminal run returns HTTP 204 to stop automatic reconnection. A request with earlier cursor replays remaining events, including the terminal event, then closes.

Heartbeats use SSE comments, for example `: keepalive`, and carry no ID. A connection failure has no implication for run status. Browser EventSource hides HTTP error details. On stream error, close it, fetch a new snapshot, and reconnect with bounded exponential backoff for transient failures. Surface snapshot 404 to the user. Use a fresh snapshot on 409/410 cursor errors when using fetch-based SSE. The backend rejects malformed or negative cursors with 422, future cursors with 409, and expired cursors with 410. Replay is retained for the lifetime of the run in the MVP. The 410 response reserves an explicit recovery path for future retention limits.

The reference reducer is `backend/contracts/tool.py`. `run.updated` replaces status/timestamps/error, `step.updated` replaces a state by step_id, `artifact.created` adds an immutable reference, `evaluation.completed` adds by evaluation_id, `review.requested` sets pending_review, and `review.decided` clears it. Every applied event updates updated_at to occurred_at and last_event_id to event_id. Review lifecycle changes and their run/step status events are committed as one transaction. A snapshot observes the completed transaction.

The backend implementation must configure CORS for Surya's actual development origin and expose Content-Disposition for downloads. The frontend can configure `VITE_API_BASE_URL=http://localhost:8000` locally. Provider keys belong exclusively in backend configuration.

## Errors and exports

All documented non-2xx JSON bodies use `{ "error": { "code": "...", "message": "...", "retryable": false } }`. Codes are machine-readable strings, and clients must tolerate new codes. Expected codes include `not_found` (404), `state_conflict` and `event_cursor_ahead` (409), `event_cursor_expired` (410), `validation_error` (422), and `service_unavailable` (503). The implementation must adapt FastAPI validation errors to this envelope.

Exports are available for succeeded and partial runs. Other statuses return 409. Unknown runs return 404 and invalid formats return 422. Partial exports visibly identify missing/degraded sections and contain available artifacts. Responses use the format's media type and Content-Disposition attachment filename. Export bytes are outside the JSON fixtures. Start requests create a new run each time. Automatic POST retries after an uncertain response are deferred until start idempotency is designed.

## Regeneration and checks

From the repository root, using the existing Python environment and pinned backend requirements, run the following commands. They import only the contract modules, require no credentials or running services, and do not load backend settings.

```powershell
.\.venv\Scripts\python.exe -m backend.contracts.tool
.\.venv\Scripts\python.exe -m backend.contracts.tool --check
```

The first command regenerates OpenAPI, SSE JSON Schema, and wire-format SSE fixtures. The second validates checked-in examples and event payloads with their source Pydantic models, verifies contiguous IDs and artifact/step references, replays both scenarios to their expected final snapshots, checks duplicate delivery and every reconnect boundary, and rejects schema or wire-fixture drift. It performs no writes. Pydantic 2.9.2 and FastAPI 0.115.0 are pinned in backend/requirements.txt. A JavaScript mock can serve events.sse with Content-Type text/event-stream and snapshot/artifact files as JSON. The fixtures contain synthetic data.

Changing a model requires regenerating schemas and updating affected fixtures. Breaking field, enum, or event changes require a new major API version. MVP request/response models reject extra fields, so even additive changes require an explicit version and consumer compatibility review.
