# React cutover readiness

The candidate tested locally was `baeeda7` with the frontend session-expiry fix on `release/react-cutover-readiness`. The previous main tested for rollback was `2115d35`. Keep the legacy frontend available until staged parity passes.

## Checks performed

| Check | Result |
| --- | --- |
| Shared REST and SSE contracts | `python -m backend.contracts.tool --check` validated both fixture tapes, replay boundaries, examples, and schema consistency. `python -m pip check` passed. |
| Backend regressions | `python -m unittest discover -s backend/tests -v` passed 24 tests against disposable PostgreSQL. They cover worker restart and lease fencing, hung and stale provider termination, recovery capacity, output validation, owner isolation, owner-scoped history, partial results, and exports. |
| Frontend | `npm run lint`, `npm test` (15 tests), `npm run build`, and `npm run build:live` passed. |
| Browser with real local stack | One successful fake-provider run, one injected pricing failure, and one queued run with an expiring token. A forced SSE disconnect let pricing finish during the outage. The browser recovered from the snapshot cursor, displayed four unique artifacts on success, and full wire replay matched the final snapshot. Anonymous snapshot/stream requests returned `401` and another owner received `404`. Reauthentication reopened the same route after the expired token and run view were cleared. The partial run reopened from history with saved outputs and a blocked-dependency explanation. |
| Review | The worker has no review route. Playwright used contract fixtures to verify checkpoint conflict recovery, approval followed by SSE resume, and the revision-request preview. |
| Exports | Successful and partial runs returned PDF, Markdown, and PPTX attachments with the expected MIME types and filenames through the local proxy. All formats included partial notices on partial runs, and the successful artifacts preserved the Starter tier. Chromium downloaded Markdown and PPTX. The PDF download did not start within the browser check window, despite a valid PDF HTTP response. |
| Repository release automation | No tracked CI workflow or candidate check runs were found. GitHub listed only its Copilot review workflow. GitHub metadata listed no staging environment or deployment target. |

The regression suites are deterministic. The v1 worker uses a fake provider, and the repo has no dedicated quality-eval suite, durable budget enforcement, or capability-compatible provider fallback. No staging calls or paid provider calls were made. There is no live quality, latency, or cost baseline for this candidate.

## Rollback rehearsal

Both the previous React live build and the previous legacy Next.js build rebuilt from archived source. The candidate's SQL migration was unchanged from the previous revision and applied twice to an isolated database. The previous API booted on those tables, read a completed v2 run and its artifacts and replay, and submitted a v1-manifest run. The previous worker completed that v1 run.

The previous worker also claimed and completed a queued `fake-business-v2` run. It lacks the candidate's manifest-version claim filter and v2 validation. Before a worker rollback, pause admission of newer runs and drain them with a compatible worker, or isolate their queue. Rehearse that sequence on staging before swapping worker versions.

The legacy prompt code and model map were unchanged between the tested revisions. The v1 worker pins the fake workflow version, but there is no published previous deployment artifact or versioned live prompt/model profile to restore and verify here.

## Gates before routing traffic to React

- Verify the staging issuer and browser token renewal, owner isolation, same-origin SSE proxy recovery, history, and all three browser downloads. Keep the legacy routes available according to the staging exposure decision.
- Verify a real review gate and review/resume end to end once the worker exposes the shared endpoint. Agree on revision approval semantics before enabling revision requests live.
- Add the live-provider adapter, fallback policy, durable budget and attempt metrics, and the deterministic quality eval gate. Record a live baseline only with an approved staging target, credentials, workload, and budget.
- Confirm the previous deployment artifact and model/prompt profile, and rehearse a rollback with the queue isolated or drained. Review deployment and legacy removal separately.
