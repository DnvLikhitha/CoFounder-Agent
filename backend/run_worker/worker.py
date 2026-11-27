"""Run `python -m backend.run_worker.worker --once` or omit --once to poll."""
import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import logging
import time

import psycopg

from backend.config import settings
from backend.run_worker.live_agents import live_provider
from backend.run_worker.provider_call import ClaimCalls, ProviderTimeout, call_with_deadline
from backend.run_worker.store import LostClaim, Store
from backend.run_worker.workflow import (
    FAKE_VERSIONS, LIVE_STEPS, LIVE_VERSION, InvalidOutput, PartialOutput, ProviderFailure, check_graph, fake_provider,
)


def execute_claim(store, claim, provider=None, lease_seconds=30):
    run_id, token = claim
    # The manifest is frozen in PostgreSQL when submitted.
    version, definitions, states = store.workflow(run_id, token)
    if provider is None:
        provider = live_provider if version == LIVE_VERSION else fake_provider
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
                except ProviderFailure:
                    store.fail(run_id, token, step_id)
                else:
                    partial = isinstance(output, PartialOutput)
                    content = output.content if partial else output
                    try:
                        store.complete_step(run_id, token, step_id, content, partial=partial)
                    except InvalidOutput:
                        store.fail(run_id, token, step_id, invalid_output=True)
                finished.add(step_id)
    store.finish(run_id, token)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    try:
        mode = settings.require_v1_provider_mode()
    except ValueError as exc:
        parser.error(str(exc))
    versions = (LIVE_VERSION,) if mode == "live" else FAKE_VERSIONS
    store = Store(settings.database_url)
    while True:
        try:
            claim = store.claim(versions=versions)
            if claim:
                execute_claim(store, claim)
        except LostClaim:
            logging.warning("Worker lease lost; discarded stale work")
        except (psycopg.Error, RuntimeError, ValueError):
            # No provider errors, DSNs, or credentials are printed.
            logging.error("Worker attempt interrupted; lease permits later recovery")
            if args.once:
                raise SystemExit(1)
        if args.once:
            return
        time.sleep(1)


if __name__ == "__main__":
    main()
