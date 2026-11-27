# CoFounder Agent run UI

This standalone Vite + React JavaScript app sits alongside `frontend/`. It consumes v1 schemas and fixtures directly from `shared/contracts/`.

## Run locally

Use Node 22.13+ on the 22.x line or Node 24+. From the repository root in PowerShell:

```powershell
cd frontend-vite
npm.cmd ci
npm.cmd run dev
```

Open the URL printed by Vite, usually `http://localhost:5173`. On macOS or Linux, use `npm` in the commands. Mock mode starts by default. Choose a success or partial-results scenario, submit the form, then approve the review. History also contains completed examples of both scenarios. Mock runs persist in the browser's local storage for this origin, so use sample problem statements.

For live mode, start a FastAPI worker serving the v1 endpoints and run:

```powershell
npm.cmd run dev:live
```

The browser uses relative `/api/v1` requests. The Vite dev server proxies them to `http://127.0.0.1:8000` by default. If the worker listens elsewhere, set `API_PROXY_TARGET=http://127.0.0.1:8001` in `frontend-vite/.env.live.local` or in the shell before starting Vite. The target is read by Vite's server configuration. Keep provider keys in the backend environment.

## Checks and builds

```powershell
npm.cmd run lint
npm.cmd test
npm.cmd run build
npm.cmd run build:live
```

Both builds write to `dist/`. The live build needs same-origin routing for `/api/v1` to the worker, including unbuffered SSE, and an SPA fallback to `index.html` for browser routes such as `/history` and `/run/:runId`.

## Integration

- History follows the v1 opaque cursor. Live listing depends on the worker's v1 history endpoint. The demo fixtures and locally submitted mock runs are browser-local. Legacy deletion is deferred from v1.
- The live UI requests Markdown, PDF, and PowerPoint exports for succeeded and partial runs. The worker must supply export bytes and attachment filenames. The shared fixtures supply artifact content and references. Mock mode leaves export downloads unavailable.
- The live client uses the shared snapshot and SSE schemas to check run state. The worker's actual streaming, history, and export behavior need joint verification when the v1 handlers are running.
