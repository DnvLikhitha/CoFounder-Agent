# PostgreSQL run worker

Live mode queues the 16 existing Groq-backed agents under the `live-startup-v1` manifest. Fake mode queues the deterministic four-step demonstration. PostgreSQL stores the authoritative snapshot, immutable artifacts, ordered events, submission identity, and expiring claim. Run a separate worker process to execute queued work.

## Scope and contract follow-up

The v1 API supports submission, snapshots, event replay, both artifact reads, owner-scoped history, and Markdown, PDF, and PPTX downloads. History uses the contract's descending `(created_at, run_id)` order and opaque cursor. Review decisions and quality evaluations remain integration work. Published evaluation records indicate `not_evaluated`.

The following additions require a separate shared-contract PR before Surya integrates authentication and submission retries.

- Optional `Idempotency-Key` request header, scoped to the authenticated owner. Retain one key per submission and reuse it on retry. The same key and normalized body return the original 202 queued snapshot, even after execution completes. Fetch the current snapshot afterward. Conflicting input returns 409. Omitting the header creates a new run per request, as the merged contract specifies. Keys remain reserved for the lifetime of the run.
- Bearer authentication with HS256 JWT, required `sub`, `exp`, `iss`, and `aud` claims, plus 401 and authentication-configuration 503 errors. Owner identity is exclusively the verified subject. Other owners receive 404 for snapshot, artifacts, events, and exports. History lists only the caller's runs. The service must configure a dedicated secret of at least 32 characters. The secret remains on the backend. Production token issuance and rotation remain follow-up work.
- The browser must use fetch-based SSE with an Authorization header for this slice. Native EventSource cannot set that header. Reconnect with the last applied event ID, either in Last-Event-ID or `after`. The header takes precedence, including zero. Close after terminal run.updated or HTTP 204. Streams close when their token expires; renew the token and reconnect. Replay is retained for the lifetime of the run.

New records live in `v1_runs`, `v1_artifacts`, and `v1_events`, so legacy endpoints continue using their existing tables. Existing Supabase helpers perform independent HTTP calls and swallow database errors, which cannot provide the atomic writes this worker needs. The new store uses direct PostgreSQL transactions and can target the same PostgreSQL/Supabase database through DATABASE_URL. Export generation reuses RunContext and the existing generators. Fake results are labelled as demonstrations and partial exports identify missing workflow sections.

## Persistence and recovery

The additive schema migration is explicit and safe to repeat. Apply it before starting the new API or worker. The database role must be able to create the three tables during migration and perform runtime SELECT/INSERT/UPDATE operations afterward. Schema changes to existing legacy tables are unnecessary.

A claim uses SELECT FOR UPDATE SKIP LOCKED, a random claim token, and a 30-second expiry measured by the database clock. Each mutation locks the run row, validates the token and expiry, then validates expiry again at the final snapshot update. A stale attempt rolls back its artifact, status, and events together. While providers are active, the coordinator waits at most one third of the lease duration before its next renewal. If the worker stops renewing, another worker can reclaim the run and recompute interrupted steps. Completed steps are recovered from PostgreSQL and skipped. Provider call deadlines remain separate from the worker lease.

Each step completion inserts one immutable artifact, updates step state, appends artifact/step/evaluation events, and updates the snapshot in one transaction. Retrying the same artifact and content during an active claim returns the original artifact without new events. Different content conflicts. Per-run row locking serializes event allocation, and rolled-back transactions leave no event ID gaps. Terminal status has its own atomic snapshot/event transaction. A crash before that transaction is recovered by the next claim. Provider failures produce partial or failed results with sanitized errors.

The claiming worker schedules up to `V1_STEP_CONCURRENCY` steps per run, with a default of two and a permitted range of one to eight. Market and competitor research can overlap. Pricing and risk can overlap after business model commits and any optional inputs settle. Financials waits for the committed business model and pricing artifacts. Other dependencies are in `workflow.py`. Registration and execution reject missing dependencies and cycles.

The manifest version stored at submission selects the provider, optional inputs, and output models for every attempt. Live workers claim only `live-startup-v1`. Fake workers can drain either historical fake manifest. Drain existing queued fake runs before switching a queue to live, or run a separate explicitly configured fake worker in a development environment. When changing a step contract, add a workflow version and retain the old specification and model classes so existing runs can finish. The live scheduler waits for optional producers to settle, then supplies their artifacts only if they completed successfully. A failed optional producer does not block its consumer. Required inputs come from the stored manifest and must have a succeeded step and committed artifact.

Each live step uses the existing agent's research tools, prompt builder, and parser with a new private context hydrated from committed inputs. It never calls the legacy retry-and-fallback runner. Validated JSON is the only path to successful publication. SerpAPI and FRED evidence is persisted separately from model estimates in `tool_evidence`, and `analysis_basis` records whether such evidence was available. Financial assumptions retain their existing `assumptions` field. These labels do not independently verify model claims.

A provider returns structured content on success, or `PartialOutput(content)` for usable but incomplete work. The worker validates either payload before publication. Invalid content fails the step with `invalid_output` and publishes no artifact. A failed, partial, or skipped required upstream makes its dependent step `skipped` with error code `dependency_blocked`. Independent steps continue. The final run is partial when required work is incomplete and artifacts are available, or failed when required work is incomplete and no artifacts are available.

## Proposed follow-up PRs

1. Freeze the prompt and model profile version per run. Harden provider retries and fallback with bounded backoff, Retry-After, durable cost reservations, and attempt accounting.
2. Add task-completion, grounding, and relevance checks on labeled evidence fixtures. Publish evaluation outcomes through the existing evaluation event and run deterministic regressions in CI.
3. Persist immutable artifact revisions and implement one target-pricing review gate. Bind approvals to the exact revision, persist the decision and event atomically, and resume financials from the approved pricing artifact after retries or reclaim.

Each provider attempt runs in a spawned child process. Use an importable provider callable and initialize any network client in the child. The worker enforces a wall-clock deadline configured by `V1_PROVIDER_TIMEOUT_SECONDS` (default 120 seconds). On timeout it terminates and joins the child, records `provider_timeout` for the step, and continues independent work. When renewal or publication detects claim loss, the coordinator terminates its active provider children before joining the executor threads. A remote provider may still complete a request already sent, so adapter-side request deadlines and retry budgets remain relevant.

## React integration

The existing v1 OpenAPI and SSE schemas already support variable-length manifests and arbitrary JSON artifact content. In live mode, derive labels, phase groups, and required dependency edges from the run's 16-step manifest. Each step's ID is also its artifact kind. `problem_refined` is an object carrying a `problem_refined` string, `customer_personas` is an array, and `pitch_deck` carries a `slides` array. The Groq response fixture in `backend/tests/fixtures/live_agent_outputs.json` exercises the original response shapes before normalization. Existing fake runs still have four steps. V1 exports render committed live content and include partial-result notices when steps fail. PPTX includes the generated slides and speaker notes when available.

## Local setup

Use Python 3.11 and PostgreSQL. The existing root docker-compose.yml provides a local postgres service if Docker is available. Alternatively, use an existing PostgreSQL instance. Configure ignored backend/.env or the process environment using placeholders below. DATABASE_URL must be a direct `postgresql://` connection string accepted by psycopg, without a SQLAlchemy `+asyncpg` suffix.

```dotenv
DATABASE_URL=postgresql://<user>:<password>@localhost:5432/<database>
V1_JWT_SECRET=<random-secret-at-least-32-characters>
V1_JWT_ISSUER=cofounder-agent
V1_JWT_AUDIENCE=cofounder-api
V1_PROVIDER_MODE=live
GROQ_API_KEY=<approved-groq-key>
SERPAPI_API_KEY=<optional-search-key>
FRED_API_KEY=<optional-macro-data-key>
```

Use the same mode and database in the API and worker. Set `V1_PROVIDER_MODE=fake` explicitly for a provider-free demonstration in development. An unset mode, fake mode in production, or a missing live Groq key prevents v1 submission and worker startup. With optional research keys omitted, agents can still run and record that they lacked external evidence. The legacy FastAPI routes retain their existing behavior and access rules.

From the repository root in PowerShell, install dependencies, migrate, and start the API.

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m backend.run_worker.migrate
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

In a second terminal with the same configuration, start the worker.

```powershell
.\.venv\Scripts\python.exe -m backend.run_worker.worker
# Consume at most one queued or expired run, then exit
.\.venv\Scripts\python.exe -m backend.run_worker.worker --once
```

For local development, obtain a short-lived token from a trusted issuer configured with the same secret, issuer, and audience. This PowerShell snippet mints a local test token into a shell variable without writing it to a file. Never give the signing secret to the frontend.

```powershell
$runToken = @'
import time
from jose import jwt
from backend.config import settings
assert len(settings.v1_jwt_secret) >= 32
print(jwt.encode({'sub': 'local-likhitha', 'exp': int(time.time()) + 900,
                  'iss': settings.v1_jwt_issuer, 'aud': settings.v1_jwt_audience},
                 settings.v1_jwt_secret, algorithm='HS256'))
'@ | .\.venv\Scripts\python.exe -
$runHeaders = @{ Authorization = "Bearer $runToken"; 'Idempotency-Key' = [guid]::NewGuid().ToString() }
$runBody = @{ problem = 'Help students discover relevant internships.' } | ConvertTo-Json
$run = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/runs -Headers $runHeaders -ContentType application/json -Body $runBody
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/runs/$($run.run_id)" -Headers $runHeaders
```

Keep `$runHeaders` to retry the same submission. Stream using a fetch-based SSE client or curl with the bearer header, and use the returned artifact hrefs against the backend origin. API and worker must point to the same database. An unavailable database returns a sanitized 503 rather than an accepted run.

## Checks

The tests use standard-library unittest and a real PostgreSQL database. TEST_DATABASE_URL must point to a disposable local test database with CREATE SCHEMA privileges. Each invocation creates a unique schema, applies the migration, truncates only its own tables between tests, and drops that schema afterward. Tests never connect to DATABASE_URL. The worker subprocess receives the isolated test connection string explicitly.

```powershell
$env:TEST_DATABASE_URL = 'postgresql://<test-user>:<test-password>@localhost:5432/<test-database>'
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
.\.venv\Scripts\python.exe -m backend.contracts.tool --check
.\.venv\Scripts\python.exe -m pip check
```

The 16-agent integration uses the real scheduler, subprocess boundary, agent prompts and parsers, and the Groq adapter with deterministic transport doubles. It checks committed dependency reads, parallel scheduling, evidence, replay, recovery, owner isolation, partial failures, and report content. Provider-free verification does not measure live output quality, cost, or latency. Use approved credentials and a bounded workload before attempting live verification.

Before staging, configure a trusted token issuer, the database connection, secret handling, and the frontend's bearer/SSE integration. The legacy demo routes retain their existing access behavior and need a separate staging exposure decision. No deployment is performed by these commands.
