# CoFounder Agent run UI

This standalone Vite + React JavaScript app sits alongside `frontend/`. It consumes v1 schemas and fixtures directly from `shared/contracts/`.

## Run locally

Use Node 22.13+ on the 22.x line or Node 24+. From the repository root in PowerShell:

```powershell
cd frontend-vite
npm.cmd ci
npm.cmd run dev
```

Open the URL printed by Vite, usually `http://localhost:5173`. On macOS or Linux, use `npm` in the commands. Mock mode starts by default. Submit a success or partial-results scenario to exercise the review. The success fixture includes an example source and assumption. Use **Approve** to resume over SSE, or **Request revision** to preview submitting feedback against the current checkpoint and its artifact IDs. History also contains completed examples of both scenarios. Mock runs persist in the browser's local storage for this origin, so use sample problem statements.

For live mode, start both the FastAPI API and the separate PostgreSQL worker. Follow the [worker setup and local token instructions](../backend/run_worker/README.md#local-setup), then run:

```powershell
npm.cmd run dev:live
```

On **Connect to the run API**, enter the short-lived bearer token from the local token instructions. Keep the JWT signing secret in the backend. The app keeps the token in this tab's session storage so a refresh can resume the run. If the API returns HTTP 401, the app clears the token and run view and prompts for a replacement. **Disconnect API** also clears the local session. This is a local integration flow pending production sign-in and token refresh.

The browser uses relative `/api/v1` requests. The Vite dev server proxies them to `http://127.0.0.1:8000` by default. If the worker listens elsewhere, set `API_PROXY_TARGET=http://127.0.0.1:8001` in `frontend-vite/.env.live.local` or in the shell before starting Vite. The target is read by Vite's server configuration. Keep provider keys in the backend environment.

## Checks and builds

```powershell
npm.cmd run lint
npm.cmd test
npm.cmd run build
npm.cmd run build:live
```

Both builds write to `dist/`. The live build needs same-origin routing for `/api/v1` to the worker, including unbuffered SSE, and an SPA fallback to `index.html` for browser routes such as `/history` and `/run/:runId`.

See the [React cutover readiness report](RELEASE_READINESS.md) for the tested candidate, rollback rehearsal, and staging gates.

## Integration

- Live history follows the worker's v1 opaque cursor. The worker does not yet emit founder checkpoints or accept review decisions. The shared v1 review route uses `review_id` and accepts `approve` or `reject`, with optional feedback. The frontend sends either decision using the v1 payload and waits for SSE to update the run. An HTTP 409 refreshes the snapshot and reloads the active checkpoint.
- The live UI downloads Markdown, PDF, and PowerPoint for succeeded and partial runs. The worker produces demonstration exports from the fake workflow. Mock mode supplies artifact content and references.
- The live client uses the shared snapshot and SSE schemas to check run state. Bearer authentication follows the worker's documented runtime behavior. Authentication and token renewal still need cross-review for the shared contract and staging.

### Shared contract follow-ups

- Artifact detail validates the v1 payload and uses the immutable `artifact_id` to show the exact revision. Evidence and assumptions in the generic JSON body are optional conventions. Agree on typed source references, assumption identifiers, and revision metadata before relying on them across producers.
- The UI shows each evaluation record's own outcome, score and reasons. Agree on dimension IDs, labels and missing-score semantics for evaluations that report several dimensions in one record.
- Agree on a checkpoint/revision precondition, an explicit revise action, and the resulting receipt and SSE transitions. The mock preview checks the checkpoint and artifact IDs without changing v1 events. It records a revision request and leaves that checkpoint pending. The current API cannot submit an explicit revision precondition or process a revision request.
