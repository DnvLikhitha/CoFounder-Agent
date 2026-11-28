# CoFounder-Agent release-readiness verification

This document records an earlier candidate. See the [final local verification](../final-project-verification.md) for the maintained application and current results.

**Verdict: NOT READY FOR DEPLOYMENT.** The Groq endpoint bug is fixed and a real browser run proved generation, artifacts, and pricing approval after a worker restart. The run finished partial. Financial Projections and Risk Analyst failed validation, downstream investor artifacts were blocked, and the browser PDF download and hosted Supabase release gates are still open.

## Candidate and architecture

The baseline is `main` at `d5d87926e09f9141cdb865741e9413046da75524`. First-parent history contains merged feature PRs #1–#15, including #12 for LangGraph, #13 for Supabase browser auth, #14 for evaluations and review, and #15 for frontend evidence and review. The backend fixes in this report are on local branch `fix/backend-release-readiness`, based on that commit. GitHub Actions passed both jobs on the merged baseline. [Application checks](https://github.com/DnvLikhitha/CoFounder-Agent/actions/runs/46130155548)

The active browser app is Vite, React, and JavaScript. It proxies `/api/v1` to FastAPI, uses Supabase sessions, and consumes the shared REST and SSE schemas. A separate worker advances `startup-reviewed-v1` in LangGraph, with PostgreSQL checkpoints and lease-fenced application state. PostgreSQL also stores artifact history, public events, review receipts, and Groq usage and attempt reservations. The worker runs the specialized agent prompts. SerpAPI and FRED supply research only where the agent calls those integrations. LangGraph pauses at the pricing checkpoint when enabled. The API mounts the v1 routes. The legacy frontend and historical workflow handlers remain in the repository.

## Tested environment and actual workflow

- Used disposable PostgreSQL 18.1 on loopback. The worker and checkpointer migrations ran twice successfully. The configured remote database was left untouched.
- Real FastAPI and a live-mode worker booted with production auth settings. `/health` and `/ready` each returned 200. Readiness exercised the configured Supabase JWKS and checked the migrated database and the live worker heartbeat.
- The browser opened the live Vite application with the configured browser-public Supabase key. The protected history route redirected to sign-in. At 390 × 844, both fields had labels, Tab moved from Email to Password, and the page had zero horizontal overflow and no page errors. The anonymous API request through the Vite proxy returned 401. Hosted login, logout and refresh require disposable sign-in credentials. The repository describes password sign-in for provisioned accounts and has no signup form.
- Submitted the representative EdTech idea for India through real React, FastAPI, SSE, the separate LangGraph worker, disposable PostgreSQL, and the configured Groq endpoint. Browser authentication used an intercepted identity response to issue a signed local test JWT. The API, research and model requests were real. The run used a 500,000-token ceiling, a $0.25 application-estimated Groq cap, enabled pricing review, and disabled optional LLM judging.
- The initial run `d73efd7a-a464-48bd-b162-6bafabec5bfa` failed in 7.130 seconds, with its first agent event at 4.129 seconds, one rejected provider attempt, and no artifacts. A rotated-key retry `fdfb85be-8f2c-476c-94f3-8a7ae0fd2c64` produced a sanitized HTTP 404. The SDK transport test reproduced the doubled `/openai/v1` prefix, even though the non-generating model catalog listed both models. Both rejected runs recorded zero usage. Correcting the adapter's base URL let the next run generate real completions.
- The corrected run used the supplied rotated key and the existing two models available on Groq's Free plan. One-agent concurrency reduced quota pressure. The full regression independently tested parallel scheduling at the usual concurrency. The ledger uses the published tariffs as an estimate. No invoice or account billing data was collected. [Groq Free plan limits](https://console.groq.com/docs/rate-limits) · [Groq model pricing](https://console.groq.com/docs/models)
- Native LangGraph pricing review was exercised in the corrected run. The first worker exited with 12 artifacts committed and `awaiting_review` persisted. After a browser refresh, an approval returned 200. A fresh worker resumed the same thread, and no committed artifact was rerun. The duplicate receipt returned 200 with its original body, a stale decision returned 409, and a foreign owner received 404. The full replay of 68 SSE events matched the final snapshot. PostgreSQL retained 11 checkpoints.
- Actual SerpAPI research was retained by Idea Generator, Market Research and Competitor Analysis, and FRED observations were retained by Market Research. An independent no-quota SerpAPI Account API probe returned 200 and a separate FRED adapter probe returned an observation. [SerpAPI Account API](https://serpapi.com/account-api)

### All 16 agent results

| Agent | Corrected real submission | Step duration | Heuristic evaluation |
| --- | --- | ---: | --- |
| Problem Refiner | Published | 2.887 s | Passed, 1.0 |
| Idea Generator | Published | 6.272 s | Passed, 1.0 |
| Market Research | Published | 8.090 s | Needs review, 0.8 |
| Competitor Analysis | Published | 7.956 s | Needs review, 0.8 |
| Customer Personas | Published | 9.547 s | Passed, 1.0 |
| Product Designer | Published | 5.442 s | Passed, 1.0 |
| MVP Roadmap | Published | 6.483 s | Passed, 1.0 |
| Business Model | Published | 4.216 s | Passed, 1.0 |
| Pricing Strategy | Published and approved | 5.685 s | Passed, 1.0 |
| Financial Projections | Invalid output | 23.692 s | Failed, 0 |
| Risk Analyst | Invalid output | 19.459 s | Failed, 0 |
| Technical Architecture | Published | 4.772 s | Passed, 1.0 |
| Database Schema | Published | 10.397 s | Passed, 1.0 |
| Security and Compliance | Published | 14.379 s | Passed, 1.0 |
| Pitch Deck | Blocked by Financial Projections | — | — |
| Executive Summary | Blocked by Financial Projections | — | — |

The deterministic full-flow test exercised the real prompts, output parsers, worker, checkpoint store, and Groq adapter with simulated provider and research responses. It verified committed dependencies, concurrent market and competitor nodes, all schemas, revisions, and downstream failure propagation. The wider PostgreSQL suite verified budget reservation concurrency, retry and fallback, recovery from provider and checkpoint failure, stale worker fencing, and reuse of committed outputs.

### Live measurements

| Measurement | Result |
| --- | --- |
| Run ID | `a4d88a3d-3986-43a2-b8ce-161163946e49` |
| Submission to first agent progress event observed by the SSE probe | 3.370 s |
| Run creation to final partial publication | 138.590 s, including review and process restart |
| Completion requests | 18 total, 14 successful responses, 4 rate-limited responses |
| Retries and fallback | 4 retries, all 4 returned using the fallback |
| Returned models | `openai/gpt-oss-120b` 10 times, `openai/gpt-oss-20b` 4 times |
| Provider-reported usage | 9,898 input tokens, 26,158 output tokens, 36,056 total |
| Ledger estimate | $0.014048325 at pinned tariffs. Provider billing unverified. |
| Agent outcomes | 12 completed, 2 failed, 2 blocked |
| Deterministic evaluations | 10 passed, 2 need review, 2 failed |
| LLM evaluations | Disabled for the baseline |

Step durations use the first start and terminal step events. Pricing excludes founder wait time. The slowest steps were Financial Projections, Risk Analyst and Security and Compliance. The first two include provider backoff. Financial Projections used all 4,096 allowed completion tokens. Truncation is possible, and the attempt record does not establish the final response's finish reason. Risk Analyst used 2,755 completion tokens. Both unusable outputs were rejected before artifact publication.

### Generated output inspection

- The refined problem and two personas focused on Indian college students, inconsistent curricula, exam preparation, and study gaps. The product plan had six core features, and the roadmap had three sprints over six weeks. The business model proposed two revenue streams and fed the pricing step.
- Market Research retained five SerpAPI links and FRED context. Competitor Analysis retained eight SerpAPI links and identified tools including Khanmigo, Google AI Pro, Flint, and MagicSchool. Several target K–12 or general audiences. Comparisons specifically for Indian college students need stronger evidence. The evaluation found contextual research references rather than claim-level links for both artifacts. Market-size estimates and the cited coverage should be reviewed before investor use. The FRED observations supply US macro context and do not establish Indian market conditions.
- Pricing produced three USD tiers from freemium to enterprise. Approval validated the workflow and recorded the decision. It did not establish local willingness to pay. The missing financial artifact prevents reconciliation of approved prices to a forecast, and no risk mitigation artifact was available to inspect.
- The architecture proposed Next.js, FastAPI and Supabase PostgreSQL for the startup concept. A PostgreSQL parser accepted 18 statements in the generated SQL artifact, which listed 16 entities. No generated DDL was executed. Runtime feasibility, migrations and capacity estimates require later validation. The Security and Compliance artifact provided six launch checklist items, with no real deployment to audit for compliance.
- The pitch deck and executive summary were blocked. Their content and financial accuracy remain unverified on real data. The heuristic rubric reports evidence and selected consistency checks and provides no independent factual validation.

## Review, browser, security, and exports

| Area | Actual application or infrastructure | Controlled regression evidence and remaining boundary |
| --- | --- | --- |
| Review and revisions | Real pricing interrupt, refresh while awaiting review, browser approval, worker restart, resume, stale rejection and idempotent duplicate passed. | Reject, revise, annual-only finance recomputation, new artifact lineage, and dependent regeneration passed with deterministic providers and PostgreSQL. A real approved revision and updated investor outputs remain open. |
| Frontend | Real React submitted and displayed pricing review and partial results, reconnecting after refresh. The real history API included the corrected run. In a separate browser check the earlier failed run reopened from history, rendered its error state, and signed out using local test identity. The corrected browser run recorded zero uncaught page errors and one console error. Hosted sign-in page and protected redirect were checked separately. | Browser and unit suites covered session renewal, duplicate submission intent, concurrent progress, SSE reconnect and replay, revision and evidence display, finance views, pitch preview, and download interactions with controlled data. A completed fixture dashboard showed the finance revision and deck on the real app, with no page overflow at 390 pixels. Hosted sessions and comprehensive accessibility remain open. |
| Security | Production-mode probes returned 401 for missing and invalid credentials, 404 for the retired route, and omitted CORS permission for an unapproved origin. The authenticated local test returned 404 for foreign snapshot, artifact, SSE and review requests and 401 for an expired token. A build using the public key contained none of six configured server credential values across four JavaScript bundles. | PostgreSQL and browser regressions covered redaction, safe rendering and session renewal. Repeat the owner checks with two hosted test users and the staging ingress. |
| Live partial exports | The browser saved Markdown and PowerPoint. The PDF browser download timed out. Downloaded all three directly with an authenticated HTTP client and opened them. The PDF had 12 extractable pages, Markdown had 399 lines, and PPTX contained one cover because the pitch was blocked. All contained the generated startup name and missing-sections notice. PDF and Markdown marked finance unavailable. | File validity, filenames and content passed. The browser PDF path remains open even though the API PDF opened and contained the generated SQL and security material. Visual layout and a complete generated investor deck remain unverified. |
| Deterministic exports | Real HTTP downloads from the labelled fixture run were opened and parsed. A revised, then approved run produced a six-page PDF, 13-slide PPTX and UTF-8 Markdown. All three contained the $14,400 ARR fixture. | A rejected fixture review produced a five-page PDF, one-slide PPTX and Markdown. All three retained the missing-sections notice. |

## Issues and changes

| Severity | Finding | Disposition |
| --- | --- | --- |
| Critical | The pinned Groq SDK appended `/openai/v1` a second time to the configured base URL. Real completions returned 404. | Fixed the base URL, added a transport assertion for the exact path, and verified actual completions from both primary and fallback. |
| High | Financial Projections and Risk Analyst failed validation in the corrected real run. The missing forecast blocked both investor agents. | Open. Output validation worked as designed. Establish the exact causes and verify complete outputs on a new approved test run. |
| High | No two hosted Supabase test accounts were available. | Hosted login, renewal, and cross-user tests remain release gates. Public JWKS and local security paths passed. |
| Medium | Edge did not save the real PDF through the app even though the authenticated PDF API returned a valid report. | Open for frontend and ingress investigation. Preserved the API media type and corrected export contents. |
| Medium | PDF omitted published persona, product, roadmap, business model, architecture, database, security, and pitch-deck content. | Added the missing sections to the backend PDF generator. The regression test checks content from committed artifacts, and the downloaded PDF was opened and parsed. |
| Medium | Markdown rendered absent infrastructure costs as `$0/month`. | Report now labels the estimate and renders absent values as `Unavailable`. Covered by the export regression. |
| Low | A provider rejection initially carried too little information to distinguish a bad URL from other failures. | Terminal rejection logs now contain HTTP status, category, and an allowlisted code. The rotated-key run captured the 404 safely. |
| Low | The existing frontend cutover report is a historical result for an older candidate and describes features that have since shipped. | Use this report for the current candidate. |

## Commands and results

Ran these commands from the repository root unless shown otherwise. The PostgreSQL DSN below points to the disposable instance, not the configured remote service.

```powershell
$env:TEST_DATABASE_URL = 'postgresql://postgres@127.0.0.1:55438/postgres'
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
.\.venv\Scripts\python.exe -m backend.contracts.tool --check --check-runtime
.\.venv\Scripts\python.exe -m unittest -v backend.tests.test_run_worker.WorkerIntegrationTests.test_all_live_agents_publish_committed_artifacts_and_export_real_content
.\.venv\Scripts\python.exe -m unittest -v backend.tests.test_provider backend.tests.test_live_agents.LiveAgentTests.test_versioned_prompt_bundle_matches_its_fingerprint
```

```powershell
Set-Location frontend-vite
npm.cmd ci --no-audit --no-fund
npm.cmd run lint
npm.cmd test
npm.cmd run build:live
$env:PLAYWRIGHT_CHROMIUM_CHANNEL = 'msedge'
npm.cmd run test:browser
```

The merged baseline and final local backend candidate both passed all 77 backend tests with no skips. The final run took 158.734 seconds. The focused export regression passed, and the provider transport, diagnostics and prompt-registration check passed all seven tests. `pip check` and REST/SSE contract verification passed. Frontend lint and the live build passed. All 33 frontend tests and all six Edge integration tests passed. Runtime verification used `python -m backend.run_worker.migrate`, `python -m uvicorn backend.main:app --host 127.0.0.1 --port 18041 --no-access-log`, and `python -m backend.run_worker.worker --once` with the disposable database and explicit live-mode limits. The packaged `verify:live` CLI was skipped because its real hosted account and a successful live run were unavailable.

## Deployment gates

1. Diagnose the invalid finance and risk outputs. Capture a successful full run, including generated finance and investor outputs, with an authorized test workload and recorded usage. Verify the browser PDF download against an actual report at the staging ingress.
2. Provision two disposable hosted Supabase users. Verify password sign-in, refresh, logout, owner isolation for artifacts, SSE and reviews, and the staging reverse proxy's TLS and SSE behavior.
3. Exercise a real pricing revision and approval. Reconcile the resulting forecast, pitch and summary with the approved pricing and confirm claim-level evidence for market and competitor statements. Measure successful latency and cost against the test budget. Budget the optional judge separately if enabling it.
4. Apply the idempotent schema migration to the approved staging database, check worker and API readiness, and rehearse rollback against the correct pinned workflow versions. Confirm production settings and a deploy approval before routing traffic or changing legacy availability.
