"""Run `python -m backend.run_worker.worker --once` or omit --once to poll."""
import argparse
from functools import partial
import logging
import time

import psycopg

from backend.config import settings
from backend.llm.profiles import PROFILES
from backend.run_worker.live_agents import PROMPT_BUNDLES, live_provider, verify_prompt_bundles
from backend.run_worker.provider_call import ClaimCalls, call_with_deadline
from backend.run_worker.store import LostClaim, Store, StoreError
from backend.run_worker.workflow import GRAPH_VERSIONS, LIVE_VERSION
from backend.safe_logging import configure_safe_logging


def pinned_live_provider(store, claim, configuration):
    profile = configuration["model_profile"]
    prompt_version = configuration["prompt_version"]
    if profile not in PROFILES or prompt_version not in PROMPT_BUNDLES:
        raise ValueError("Unsupported pinned live execution profile")
    return partial(live_provider, store=store, claim=claim, profile=profile, prompt_version=prompt_version,
                   timeout=settings.v1_provider_timeout_seconds)


def execute_claim(store, claim, provider=None, lease_seconds=30, heartbeat_mode=None, *, review_pricing=False):
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
        if configuration["llm_evaluation"] and configuration["graph_mode"] == "live":
            budgeted_judge = partial(judge_provider, database=store, claim=claim,
                                     profile=configuration["model_profile"], timeout=settings.v1_provider_timeout_seconds)

            def judge(step_id, body, upstream):
                return call_with_deadline(budgeted_judge, step_id, body, upstream,
                                          settings.v1_provider_timeout_seconds, calls)

        execute_graph(store, claim, configuration, execute, calls, lease_seconds=lease_seconds,
                      heartbeat_mode=heartbeat_mode, review=review_pricing, judge=judge)


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
        claim_options = dict(versions=GRAPH_VERSIONS)
    store = Store(settings.database_url)
    try:
        store.check_retired_runs()
    except StoreError as exc:
        parser.error(str(exc))
    except psycopg.Error:
        parser.error("Could not check workflow compatibility. Apply the worker schema and check PostgreSQL.")
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
