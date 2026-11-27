"""Run synchronous provider code inside a killable process, outside database transactions."""
from multiprocessing import get_context
from time import monotonic

from backend.run_worker.workflow import ProviderFailure


class ProviderTimeout(ProviderFailure):
    pass


def _invoke(sender, provider, step_id, body, upstream):
    with sender:
        try:
            output = provider(step_id, body, upstream)
        except Exception:
            sender.send((False, None))
        else:
            sender.send((True, output))


def call_with_deadline(provider, step_id, body, upstream, timeout):
    # Spawn avoids inheriting database connections from the multithreaded coordinator.
    context = get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_invoke, args=(sender, provider, step_id, body, upstream), daemon=True)
    deadline = monotonic() + timeout
    with receiver, sender:
        process.start()
        sender.close()
        try:
            if not receiver.poll(max(0, deadline - monotonic())):
                raise ProviderTimeout()
            try:
                ok, output = receiver.recv()
            except EOFError:
                raise ProviderFailure() from None
            process.join(max(0, deadline - monotonic()))
            if process.is_alive() or monotonic() >= deadline:
                raise ProviderTimeout()
            if not ok or process.exitcode:
                raise ProviderFailure()
            return output
        finally:
            if process.is_alive():
                process.kill()
            process.join()
            process.close()
