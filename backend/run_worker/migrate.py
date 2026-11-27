"""Apply the additive v1 tables with python -m backend.run_worker.migrate."""
from backend.config import settings
from backend.run_worker.store import Store

if __name__ == "__main__":
    Store(settings.database_url).migrate()
    print("Applied v1 worker schema")
