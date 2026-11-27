"""Run `python -m backend.run_worker.worker --once` or omit --once to poll."""
import argparse
import logging
import time

import psycopg

from backend.config import settings
from backend.run_worker.store import LostClaim, Store
from backend.run_worker.workflow import ProviderFailure, fake_provider


def execute_claim(store, claim, provider=fake_provider, lease_seconds=30):
    run_id, token = claim
    # The manifest is frozen in PostgreSQL when submitted.
    definitions = store.workflow(run_id, token)
    pending = {step["step_id"]: step for step in definitions}
    completed = set()
    while pending:
        ready = [step for step in pending.values() if set(step["depends_on"]) <= completed]
        if not ready:
            raise ValueError("Workflow contains a dependency cycle")
        step = min(ready, key=lambda item: (item["order"], item["step_id"]))
        step_id = step["step_id"]
        store.renew(run_id, token, lease_seconds)
        inputs = store.begin_step(run_id, token, step_id)
        if inputs is not None:
            try:
                content = provider(step_id, *inputs)
            except ProviderFailure:
                store.fail(run_id, token, step_id)
                return
            store.complete_step(run_id, token, step_id, content)
        completed.add(step_id)
        del pending[step_id]
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
