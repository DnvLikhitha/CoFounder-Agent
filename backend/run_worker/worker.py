"""Run `python -m backend.run_worker.worker --once` or omit --once to poll."""
import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import logging
import time

import psycopg

from backend.config import settings
from backend.run_worker.store import LostClaim, Store
from backend.run_worker.workflow import InvalidOutput, PartialOutput, ProviderFailure, fake_provider


def execute_claim(store, claim, provider=fake_provider, lease_seconds=30):
    run_id, token = claim
    # The manifest is frozen in PostgreSQL when submitted.
    definitions, states = store.workflow(run_id, token)
    finished = {name for name, status in states.items() if status in {"succeeded", "partial", "failed", "skipped"}}
    pending = [s for s in sorted(definitions, key=lambda s: (s["order"], s["step_id"]))
               if s["step_id"] not in finished]
    # Two provider calls can overlap in this graph. Only the claiming thread publishes results.
    active = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        while pending or active:
            store.renew(run_id, token, lease_seconds)
            for step in pending.copy():
                if len(active) >= 2 or not set(step["depends_on"]) <= finished:
                    continue
                step_id = step["step_id"]
                inputs = store.begin_step(run_id, token, step_id)
                pending.remove(step)
                if inputs is None:
                    finished.add(step_id)
                else:
                    active[pool.submit(provider, step_id, *inputs)] = step_id
            if not active:
                if pending and not any(set(s["depends_on"]) <= finished for s in pending):
                    raise ValueError("Workflow contains an unsatisfied dependency")
                continue
            done, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                step_id = active.pop(future)
                try:
                    output = future.result()
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
    store = Store(settings.database_url)
    while True:
        try:
            claim = store.claim()
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
