"""Run `python -m backend.run_worker.worker --once` or omit --once to poll."""
import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from functools import partial
import logging
import time

import psycopg

from backend.config import settings
from backend.llm.profiles import PROFILES
from backend.run_worker.ledger import BudgetExceeded
from backend.run_worker.live_agents import PROMPT_BUNDLES, live_provider, verify_prompt_bundles
from backend.run_worker.provider_call import ClaimCalls, ProviderTimeout, call_with_deadline
from backend.run_worker.store import LostClaim, Store, StoreError
from backend.run_worker.workflow import (
    FAKE_VERSIONS, GRAPH_VERSIONS, LIVE_STEPS, LIVE_VERSION, InvalidOutput, PartialOutput, ProviderFailure,
    check_graph, fake_provider,
)
from backend.safe_logging import configure_safe_logging


def pinned_live_provider(store, claim, configuration):
    profile = configuration["model_profile"]
    prompt_version = configuration["prompt_version"]
    if profile not in PROFILES or prompt_version not in PROMPT_BUNDLES:
        raise ValueError("Unsupported pinned live execution profile")
    return partial(live_provider, store=store, claim=claim, profile=profile, prompt_version=prompt_version,
                   timeout=settings.v1_provider_timeout_seconds)


def execute_claim(store, claim, provider=None, lease_seconds=30, heartbeat_mode=None, *, review_pricing=False):
    run_id, token = claim
    # The manifest is frozen in PostgreSQL when submitted.
    version, definitions, states = store.workflow(run_id, token)
    if version in GRAPH_VERSIONS:
        from backend.run_worker.evaluator import judge_provider
        from backend.run_worker.graph import demo_provider, execute_graph

        configuration = store.graph_configuration(*claim)
        with ClaimCalls() as calls:
            if provider is None and configuration["graph_mode"] == "fake":
                execute = demo_provider
            else:
                provider = provider or pinned_live_provider(store, claim, configuration)

                def execute(step_id, body, upstream):
                    return call_with_deadline(provider, step_id, body, upstream,
                                              settings.v1_provider_timeout_seconds, calls)

            judge = None
            if configuration["llm_evaluation"]:
                budgeted_judge = partial(judge_provider, database=store, claim=claim,
                                         profile=configuration["model_profile"], timeout=settings.v1_provider_timeout_seconds)

                def judge(step_id, body, upstream):
                    return call_with_deadline(budgeted_judge, step_id, body, upstream,
                                              settings.v1_provider_timeout_seconds, calls)

            execute_graph(store, claim, configuration, execute, calls, lease_seconds=lease_seconds,
                          heartbeat_mode=heartbeat_mode, review=review_pricing, judge=judge)
        return

    # Drain jobs pinned before the graph migration with their original scheduler.
    if provider is None:
        provider = fake_provider
        if version == LIVE_VERSION:
            provider = pinned_live_provider(store, claim, store.live_configuration(run_id, token))
    dependencies = {step["step_id"]: set(step["depends_on"]) for step in definitions}
    if version == LIVE_VERSION:
        # Wait for optional producers to settle, then pass only their committed complete artifacts.
        for name, inputs in dependencies.items():
            inputs.update(LIVE_STEPS[name].optional)
    check_graph(dependencies)
    finished = {name for name, status in states.items() if status in {"succeeded", "partial", "failed", "skipped"}}
    pending = [s for s in sorted(definitions, key=lambda s: (s["order"], s["step_id"]))
               if s["step_id"] not in finished]
    # Only the claiming thread publishes results.
    concurrency = settings.v1_step_concurrency
    active = {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool, ClaimCalls() as calls:
        while pending or active:
            store.renew(run_id, token, lease_seconds)
            if heartbeat_mode is not None:
                store.heartbeat(heartbeat_mode)
            for step in pending.copy():
                if len(active) >= concurrency or not dependencies[step["step_id"]] <= finished:
                    continue
                step_id = step["step_id"]
                inputs = store.begin_step(run_id, token, step_id)
                pending.remove(step)
                if inputs is None:
                    finished.add(step_id)
                else:
                    future = pool.submit(call_with_deadline, provider, step_id, *inputs,
                                         settings.v1_provider_timeout_seconds, calls)
                    active[future] = step_id
            if not active:
                if pending and not any(dependencies[s["step_id"]] <= finished for s in pending):
                    raise ValueError("Workflow contains an unsatisfied dependency")
                continue
            # Wake the coordinator to renew even when every provider is still busy.
            done, _ = wait(active, timeout=lease_seconds / 3, return_when=FIRST_COMPLETED)
            for future in done:
                step_id = active.pop(future)
                try:
                    output = future.result()
                except InvalidOutput:
                    store.fail(run_id, token, step_id, invalid_output=True)
                except ProviderTimeout:
                    store.fail(run_id, token, step_id, timed_out=True)
                except BudgetExceeded:
                    store.fail(run_id, token, step_id, budget_exceeded=True)
                except ProviderFailure:
                    store.fail(run_id, token, step_id)
                else:
                    is_partial = isinstance(output, PartialOutput)
                    content = output.content if is_partial else output
                    try:
                        store.complete_step(run_id, token, step_id, content, partial=is_partial)
                    except InvalidOutput:
                        store.fail(run_id, token, step_id, invalid_output=True)
                finished.add(step_id)
    store.finish(run_id, token)


def main():
    configure_safe_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    try:
        mode = settings.require_v1_provider_mode()
        if not settings.database_url:
            raise ValueError("DATABASE_URL is required")
        if mode == "live":
            verify_prompt_bundles()
    except ValueError as exc:
        parser.error(str(exc))
    if mode == "live":
        claim_options = dict(versions=(LIVE_VERSION, *GRAPH_VERSIONS), prompt_versions=PROMPT_BUNDLES,
                             model_profiles=PROFILES)
    else:
        claim_options = dict(versions=(*FAKE_VERSIONS, *GRAPH_VERSIONS))
    store = Store(settings.database_url)
    while True:
        try:
            store.heartbeat(mode)
            claim = store.claim(**claim_options, graph_mode=mode, active_limit=settings.max_concurrent_runs)
            if claim:
                execute_claim(store, claim, heartbeat_mode=mode)
        except LostClaim:
            logging.warning("Worker lease lost; discarded stale work")
        except (psycopg.Error, StoreError, RuntimeError, ValueError):
            # No provider errors, DSNs, or credentials are printed.
            logging.error("Worker attempt interrupted; lease permits later recovery")
            if args.once:
                raise SystemExit(1)
        if args.once:
            return
        time.sleep(1)


if __name__ == "__main__":
    main()
