# CoFounder Agent run UI

The Vite + React JavaScript workspace uses the durable v1 API and reads schemas and fixtures directly from `shared/contracts/`.

## Run locally

Use Node 22.13+ on the 22.x line or Node 24+. From the repository root in PowerShell:

```powershell
cd frontend-vite
npm.cmd ci
npm.cmd run dev:mock
```

Open the URL printed by Vite, usually `http://localhost:5173`. On macOS or Linux, use `npm` in the commands. The header identifies **Mock mode**. Its 16-step samples include overlapping agents, a review checkpoint, and either a complete result or a pricing timeout that blocks financial projections. Use **Approve** to resume over SSE, or **Request revision** to preview submitting feedback. History includes completed samples. Mock runs persist locally for this origin, so use sample problem statements.

### Live mode

Use an API configured to validate Supabase user JWTs and a provisioned Supabase account with email and password sign-in enabled. Use the same Supabase project as the API's `SUPABASE_URL` and confirm that it issues ES256 or RS256 user access tokens. The backend's development-only HS256 issuer cannot authenticate a Supabase session. See [the worker's production configuration](../backend/run_worker/README.md#production-configuration).

Set the public browser settings in `frontend-vite/.env.live.local` or the build environment.

```dotenv
VITE_SUPABASE_URL=http://127.0.0.1:54321
VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_your_public_key
```

Projects with legacy keys can set `VITE_SUPABASE_ANON_KEY` in place of the publishable key. The frontend accepts only browser-public keys. Keep the Supabase secret or service-role key, database credentials, and provider keys server-side.

```powershell
npm.cmd run dev
```

Supabase Auth manages the session in browser local storage and rotates its refresh token. This browser-only setup uses the provider's default storage, which is accessible to scripts on the same origin. The app looks up the current access token for each request and retries one 401 after renewal. If the API still rejects it or the provider rejects renewal, the workspace returns to sign-in and preserves the requested route. **Sign out** ends the current Supabase session.

The browser uses relative `/api/v1` requests. The Vite dev server proxies them to `http://127.0.0.1:8000` by default. Set `API_PROXY_TARGET` in `frontend-vite/.env.live.local` or in the shell to use a different HTTP or HTTPS API origin.

### Verify exports over local HTTPS

If an authenticated PDF request stalls in Chromium over local HTTP, run the live dev server over HTTPS with a trusted development certificate for your local host. Supply the paths in the shell or in `.env.live.local` and restart Vite.

```dotenv
DEV_HTTPS_CERT=C:/path/to/local-cert.pem
DEV_HTTPS_KEY=C:/path/to/local-key.pem
```

For HTTPS development, use Node 22.21.1 or later on the 22.x line, or Node 24. Node 22.21.0 crashes on secure WebSocket upgrades. [Node issue](https://github.com/nodejs/node/issues/60336)

Open the HTTPS URL printed by Vite. The dev proxy still uses `API_PROXY_TARGET`. Keep the private key outside the repository.

## Checks and builds

```powershell
npm.cmd run lint
npm.cmd test
npx.cmd playwright install chromium
npm.cmd run test:browser
npm.cmd run build
```

`npm run build` writes the live app to `dist/`. Builds reject mock mode, and live mode without Supabase settings shows a sign-in unavailable page. The live build needs same-origin routing for `/api/v1` to the API, including unbuffered SSE, and an SPA fallback to `index.html` for browser routes such as `/sign-in`, `/history`, and `/run/:runId`.

Browser tests exercise the live-mode app with intercepted Supabase and v1 responses. Set `PLAYWRIGHT_CHROMIUM_CHANNEL=msedge` or `chrome` to run against an installed browser.

See the [React cutover readiness report](RELEASE_READINESS.md) for the tested candidate, rollback rehearsal, and staging gates.

## Integration

- The dashboard uses manifest display order, step states, dependency IDs, and artifact references from v1. Output widgets recognize the artifact kinds used by the legacy agents and show generic structured data for new kinds. Missing values and unproduced artifacts remain visible as such.
- Starting a run sends an `Idempotency-Key`. Retrying unchanged input in the open form reuses the key. Editing the input, completing the submission, or choosing **Start a new submission** starts a new intent. The key is held in the open form.
- Live history follows the worker's owner-scoped v1 cursor. Enable `V1_REQUIRE_PRICING_REVIEW` to review draft pricing before investor outputs. The UI sends the selected artifact revision with each decision, supports editing one tier, and waits for the event carrying the replacement review. An HTTP 409 refreshes the snapshot. A separately enabled executive-summary review supports approval or rejection.
- Run outputs link published source references, claims, and upstream artifact revisions. Revision history lets founders open older outputs and compare two versions side by side. After approval, the run labels downstream work that is regenerating and identifies the resulting revision from its input lineage.
- Agent evaluations show the reported outcome, method, dimension explanations, and any evidence. Unevaluated outputs are labeled separately and do not display a score. Assumptions and uncertainty notes come from the artifact payload.
- In live mode, each loaded artifact can be downloaded in its original media type. The UI also downloads server-generated Markdown, PDF, and PowerPoint for succeeded and partial runs. You can cancel an export while it is preparing and use the Save link to save the prepared file again.
- REST and fetch-based SSE use bearer headers. After a stream closes, the client obtains a fresh snapshot and opens the stream at its cursor using the current session. Forbidden, rate-limited, and unavailable responses produce distinct messages and preserve the session.

### Verify all 16 outputs on the live API

Provide an existing successful live-provider run owned by a synthetic test account. Set `LIVE_API_ORIGIN`, `LIVE_SUPABASE_URL`, `LIVE_SUPABASE_PUBLISHABLE_KEY` (or `LIVE_SUPABASE_ANON_KEY`), `LIVE_TEST_EMAIL`, `LIVE_TEST_PASSWORD`, and `LIVE_RUN_ID` in the verification process environment. Run `npm.cmd run verify:live` from `frontend-vite`. The verifier signs in, reads the snapshot and each immutable artifact, and reports the result per agent. It submits no runs and makes no model calls.

### Local full-stack verification

Use the [repository setup](../README.md#run-locally-on-windows) to run React with Supabase Auth, FastAPI, PostgreSQL, and the worker. Fake-provider mode runs the full graph and labels deterministic data in reports. See the [verification report](../docs/final-project-verification.md) for the results and remaining checks.
