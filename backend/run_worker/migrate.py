"""Apply the additive v1 tables with python -m backend.run_worker.migrate."""
import psycopg

from backend.config import settings
from backend.run_worker.store import Store, StoreError

if __name__ == "__main__":
    try:
        Store(settings.database_url).migrate()
    except StoreError as exc:
        if exc.code == "retired_runs_pending":
            raise SystemExit(str(exc)) from None
        raise SystemExit("Could not apply v1 worker schema") from None
    except (psycopg.Error, ValueError):
        raise SystemExit("Could not apply v1 worker schema") from None
    print("Applied v1 worker schema")
