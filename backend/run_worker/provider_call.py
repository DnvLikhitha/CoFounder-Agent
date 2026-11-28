"""Run synchronous provider code inside a killable process, outside database transactions."""
from concurrent.futures import CancelledError
from contextlib import contextmanager
from multiprocessing import get_context
from threading import Lock
from time import monotonic

import psycopg

from backend.run_worker.ledger import BudgetExceeded
from backend.run_worker.store import LostClaim
from backend.run_worker.workflow import InvalidOutput, ProviderFailure, ProviderTimeout


class ClaimCalls:
    """Terminate active children before joining the claim's executor threads."""

    def __init__(self):
        self._lock = Lock()
        self._active = set()
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.cancel()

    def cancel(self):
        with self._lock:
            self._closed = True
            for process in self._active:
                if process.is_alive():
                    process.kill()

    @contextmanager
    def running(self, process):
        with self._lock:
            if self._closed:
                raise CancelledError()
            process.start()
            self._active.add(process)
        try:
            yield
        finally:
            with self._lock:
                self._active.remove(process)
            if process.is_alive():
                process.kill()
            process.join()
            process.close()


def _invoke(sender, provider, step_id, body, upstream):
    with sender:
        try:
            output = provider(step_id, body, upstream)
        except InvalidOutput:
            sender.send(("invalid_output", None))
        except BudgetExceeded:
            sender.send(("budget_exceeded", None))
        except ProviderTimeout:
            sender.send(("provider_timeout", None))
        except (psycopg.Error, LostClaim):
            sender.send(("interrupted", None))
        except Exception:
            sender.send(("provider_failed", None))
        else:
            sender.send(("ok", output))


def call_with_deadline(provider, step_id, body, upstream, timeout, calls):
    # Spawn avoids inheriting database connections from the multithreaded coordinator.
    context = get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_invoke, args=(sender, provider, step_id, body, upstream), daemon=True)
    deadline = monotonic() + timeout
    with receiver, sender, calls.running(process):
        sender.close()
        if not receiver.poll(max(0, deadline - monotonic())):
            raise ProviderTimeout()
        try:
            status, output = receiver.recv()
        except EOFError:
            raise ProviderFailure() from None
        process.join(max(0, deadline - monotonic()))
        if process.is_alive() or monotonic() >= deadline:
            raise ProviderTimeout()
        if status == "invalid_output":
            raise InvalidOutput(step_id)
        if status == "budget_exceeded":
            raise BudgetExceeded()
        if status == "provider_timeout":
            raise ProviderTimeout()
        if status == "interrupted":
            raise RuntimeError("Provider accounting was interrupted")
        if status != "ok" or process.exitcode:
            raise ProviderFailure()
        return output
