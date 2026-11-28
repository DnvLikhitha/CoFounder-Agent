# PostgreSQL run worker

New live and fake runs use the 16-agent `startup-reviewed-v1` manifest. Live mode uses Groq and fake mode supplies deterministic fixtures. PostgreSQL stores the authoritative snapshot, artifacts, events, and claim. The separate worker advances the graph and saves PostgreSQL checkpoints. Earlier LangGraph runs keep their existing topology and checkpoint format. See the [LangGraph architecture](../../docs/langgraph-orchestration.md) for the dependency graph and recovery behavior.

## Production configuration

Set `ENVIRONMENT=production`, `V1_PROVIDER_MODE=live`, `DATABASE_URL`, `GROQ_API_KEY`, and `SUPABASE_URL` to the exact HTTPS origin used by Supabase Auth. Configure that project to issue ES256 or RS256 user access tokens. The API validates the signature against the project's JWKS, requires the project issuer, `authenticated` audience and role, expiration, issued-at time, and a user and session UUID. It caches public keys for five minutes and refreshes on unknown key IDs, with a ten-second refresh cooldown. Allow outbound HTTPS to the configured project. Local HS256 tokens are limited to development, local, and test environments. [Supabase signing keys](https://supabase.com/docs/guides/auth/signing-keys)

Every run operation is scoped to the verified owner. Production storage keys include the issuer and subject UUID. Runs created by the earlier local issuer retain their local ownership and need a separately verified account mapping to become visible in production. The application serves only v1 run routes. Legacy history, result, delete, stream, and export paths return 404. Legacy data remains in its original tables.

Set `CORS_ORIGINS` to exact comma-separated HTTPS origins, or to an empty string for same-origin clients. Browser requests use bearer headers for REST, downloads, and fetch-based SSE. Use ingress logs that exclude query strings, headers, and bodies, and disable SSE buffering. `/health` checks liveness. `/ready` checks configuration, the migrated database schema, a worker heartbeat for the configured mode within 45 seconds, and usable JWKS in production. It makes no paid model requests.

The REST and SSE contracts describe the available decisions, revision history, and replay. [Shared run contract](../../shared/contracts/README.md)

## Evaluation and founder review

New runs record deterministic evaluations by default. All agents pass their output schema and applicable domain invariants before publication. The evaluator checks task completion, relevance, consistency, grounding, and completeness. Grounding links available SerpAPI and FRED sources and committed research revisions. It distinguishes a reported citation, a matching upstream value, and general research context. These checks flag weaknesses for review and do not independently verify research claims.

Set `V1_LLM_EVALUATION=true` to add a separate LLM judgment to new live runs. The judge uses the pinned Groq profile and the same durable token and cost limits as generation. Usage records distinguish `evaluation` from `generation` and identify the execution revision. Reserve budget for generation when enabling judging. A malformed judge response, timeout, or exhausted budget leaves the heuristic result and valid output available. Founder-edited artifacts receive deterministic evaluation.

Set `V1_REQUIRE_PRICING_REVIEW=true` to enable the checkpoint for new live or fake runs. The worker checkpoints and releases its claim after producing draft pricing and financial projections, before starting the pitch deck or executive summary. An owner can approve the displayed pricing revision, reject it, or submit changed monthly and annual USD prices for one existing tier. A change creates an immutable revision and a fresh approval request. Approval of the change queues financial recomputation, and the pitch deck and executive summary then use the approved pricing and recomputed forecast. Unaffected agents keep their results. Rejection preserves the draft history, blocks dependent investor outputs, and omits the rejected outputs from exports. Recovery uses the native interrupt and its persisted decision after any worker restart.

Both flags default to false and are pinned at submission. `V1_REQUIRE_FOUNDER_REVIEW=true` independently pauses new successful live runs for final approval of the executive summary. New runs pin `startup-reviewed-prompts-v1`, which supplies both approved monthly and annual prices to downstream agents. Apply the repeatable database migration before starting the updated API and workers. Release the Vite client with the updated API because both use strict contract validation. Earlier submitted runs retain their original behavior.

## Persistence and recovery

Stop pre-hardening workers before applying the repeatable migration, then start the new API and worker with the same database and mode. A pre-hardening worker can make unmetered calls. Use a trusted PostgreSQL role that owns the v1 relations and can create new tables during migration. The schema enables row-level security and revokes direct access from Supabase `anon`, `authenticated`, and `PUBLIC` roles. Use the direct PostgreSQL DSN for the API and worker.

A claim uses SELECT FOR UPDATE SKIP LOCKED, a random claim token, and a 30-second expiry measured by the database clock. Each mutation locks the run row, validates the token and expiry, then validates expiry again at the final snapshot update. A stale attempt rolls back its artifact, status, and events together. While providers are active, the coordinator waits at most one third of the lease duration before its next renewal. If the worker stops renewing, another worker can reclaim the run and recompute interrupted steps. Completed steps are recovered from PostgreSQL and skipped. Provider call deadlines remain separate from the worker lease.

Each step completion inserts one immutable artifact, updates step state, appends artifact/step/evaluation events, and updates the snapshot in one transaction. Retrying the same artifact and content during an active claim returns the original artifact without new events. Different content conflicts. Per-run row locking serializes event allocation, and rolled-back transactions leave no event ID gaps. Terminal status has its own atomic snapshot/event transaction. A crash before that transaction is recovered by the next claim. Provider failures produce partial or failed results with sanitized errors.

LangGraph schedules up to `V1_STEP_CONCURRENCY` steps per run, with a default of two and a permitted range of one to eight. The queue serializes admission against `MAX_CONCURRENT_RUNS` across worker processes, with a default of five. Market and competitor research can overlap. Pricing and risk can overlap after business model commits and any optional inputs settle. Financials waits for the committed business model and pricing artifacts. Other dependencies are in `workflow.py`. Registration and execution reject missing dependencies and cycles.

The submission pins its manifest and provider mode. Live workers drain unfinished `live-startup-v1` jobs with the released scheduler. Development fake workers can drain either historical four-step manifest. New submissions in both modes use LangGraph and resume only their own version. When changing a step contract, add a workflow version and retain earlier specifications while jobs can still claim them. The graph waits for optional producers to settle and passes their artifacts when they succeed. The store supplies required inputs from successful committed artifacts.

Each live step uses the existing agent's research tools, prompt builder, and parser with a new private context hydrated from committed inputs. It never calls the legacy retry-and-fallback runner. Validated JSON is the only path to successful publication. SerpAPI and FRED evidence is persisted separately from model estimates in `tool_evidence`, and `analysis_basis` records whether such evidence was available. Financial assumptions retain their existing `assumptions` field. These labels do not independently verify model claims.

A provider returns structured content on success, or `PartialOutput(content)` for usable but incomplete work. The worker validates either payload before publication. Invalid content fails the step with `invalid_output` and publishes no artifact. A failed, partial, or skipped required upstream makes its dependent step `skipped` with error code `dependency_blocked`. Independent steps continue. The final run is partial when required work is incomplete and artifacts are available, or failed when required work is incomplete and no artifacts are available.

## Provider policy and accounting

Each new live run pins its model profile, prompt bundle, and budget at submission. The migration assigns the initial profile, prompt version, and default limits to unfinished pre-ledger live runs. Their metering starts at the migration. Existing terminal results stay readable and have no retroactive usage data.

`V1_RUN_TOKEN_LIMIT` defaults to 500,000 tokens. `V1_RUN_COST_LIMIT_NANOUSD` defaults to 250,000,000 nano-USD ($0.25). The cost is estimated from the versioned Groq input/output tariff. The adapter reserves a conservative prompt bound and the full maximum completion before dispatch. Concurrent steps serialize reservations on the run row and share both limits. PostgreSQL records the requested and returned model IDs, attempt number, provider outcome, observed usage when available, and charged tokens and cost. Read `v1_llm_attempts` through the trusted database role for metering. Sum `charged_tokens` and `charged_cost_nanousd` per run for committed usage plus outstanding and uncertain reservations. Confirmed rejections release the reservation. Timeouts, uncertain errors, and abandoned reservations retain their full charge across reclaim because the provider can still bill a dispatched request. A request that cannot fit fails its step with `budget_exceeded`. [Groq models and pricing](https://console.groq.com/docs/models)

The adapter makes at most three attempts per agent across claims. The SDK's retries are off. Request deadlines are at most 20 seconds and fit within the worker's step deadline (`V1_PROVIDER_TIMEOUT_SECONDS`, default 120 seconds). Recoverable errors use bounded exponential backoff with jitter and honor `Retry-After` within the deadline. The compatible GPT-OSS 20B fallback shares the primary model's request and context capabilities. The worker terminates the child when its deadline or claim expires, then a replacement worker can recover from committed artifacts. [Groq rate limits](https://console.groq.com/docs/rate-limits)

Create a new profile version when changing models or prices. Register each new prompt renderer and its system prompt in `PROMPT_BUNDLES`. Retain earlier entries and their source code while unfinished runs reference them. Live workers verify every registered fingerprint at startup and claim only runs with supported workflow, profile, and prompt versions. They pass the stored prompt version to the provider process for both queued and reclaimed runs. Roll out workers that support the new version before switching the submission default.

The v1 fingerprint covers the registered renderer, system prompt, live step dependencies, and the local source files reached through static imports. This includes context hydration, agent research, and the code that formats tool responses and chat messages. Credentials, live tool responses, and run inputs are supplied at runtime.

## React integration

The existing v1 OpenAPI and SSE schemas already support variable-length manifests and arbitrary JSON artifact content. In live mode, derive labels, phase groups, and required dependency edges from the run's 16-step manifest. Each step's ID is also its artifact kind. `problem_refined` is an object carrying a `problem_refined` string, `customer_personas` is an array, and `pitch_deck` carries a `slides` array. The deterministic fixture in `backend/run_worker/demo_outputs.json` also drives the simulated Groq transport in tests. Existing four-step demo records remain available to their owners. V1 exports render committed live content and include partial-result notices when steps fail. PPTX includes the generated slides and speaker notes when available.

## Local setup

Use Python 3.11 and PostgreSQL. The existing root docker-compose.yml provides a local postgres service if Docker is available. Alternatively, use an existing PostgreSQL instance. Configure ignored backend/.env or the process environment using placeholders below. DATABASE_URL must be a direct `postgresql://` connection string accepted by psycopg, without a SQLAlchemy `+asyncpg` suffix.

```dotenv
DATABASE_URL=postgresql://<user>:<password>@localhost:5432/<database>
V1_JWT_SECRET=<random-secret-at-least-32-characters>
V1_JWT_ISSUER=cofounder-agent
V1_JWT_AUDIENCE=cofounder-api
V1_PROVIDER_MODE=live
V1_REQUIRE_PRICING_REVIEW=true
V1_LLM_EVALUATION=false
GROQ_API_KEY=<approved-groq-key>
SERPAPI_API_KEY=<optional-search-key>
FRED_API_KEY=<optional-macro-data-key>
```

Use the same mode and database in the API and worker. Set `V1_PROVIDER_MODE=fake` explicitly for a provider-free demonstration in development. With optional research keys omitted, agents record that they lacked external evidence.

From the repository root in PowerShell, install dependencies, migrate, and start the API.

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m backend.run_worker.migrate
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --no-access-log
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
import jwt
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
.\.venv\Scripts\python.exe -m backend.contracts.tool --check --check-runtime
.\.venv\Scripts\python.exe -m pip check
```

The 16-agent integration uses the LangGraph scheduler and PostgreSQL checkpointer, subprocess boundary, agent prompts and parsers, and the Groq adapter with deterministic transport doubles. It checks committed dependencies, parallel scheduling, evidence, replay, recovery, owner isolation, partial failures, and report content. Evaluation fixtures check the rubric and evidence, while PostgreSQL tests cover judge accounting, domain failures, stale and duplicate decisions, worker restart, immutable revisions, and targeted recomputation. Provider-free verification does not measure live output quality, cost, or latency.

GitHub Actions runs the backend suite with PostgreSQL and checks contract drift, frontend lint, Vite tests, and the live build. Staging verification requires the real Supabase issuer, two test users, an ingress, and approved Groq credentials and spend.
