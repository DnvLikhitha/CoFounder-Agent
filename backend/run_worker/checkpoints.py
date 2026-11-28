"""LangGraph's PostgreSQL saver with a transaction fence bound to a single claim."""
from contextlib import contextmanager
from threading import Lock

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import sql

from backend.run_worker.store import LostClaim

CHECKPOINT_TABLES = ("checkpoint_migrations", "checkpoints", "checkpoint_blobs", "checkpoint_writes")


def migrate_checkpoints(store):
    # Upstream setup uses CREATE INDEX CONCURRENTLY and requires autocommit.
    # The session lock spans those individual DDL transactions.
    with store.connect(autocommit=True, prepare_threshold=0) as connection:
        connection.execute("SELECT pg_advisory_lock(71894022)")
        PostgresSaver(connection).setup()
        roles = connection.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')").fetchall()
        with connection.transaction():
            for table in map(sql.Identifier, CHECKPOINT_TABLES):
                connection.execute(sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(table))
                connection.execute(sql.SQL("REVOKE ALL ON {} FROM PUBLIC").format(table))
                for role in roles:
                    connection.execute(sql.SQL("REVOKE ALL ON {} FROM {}").format(table, sql.Identifier(role["rolname"])))


def checkpoint_schema_ready(connection):
    protected = connection.execute("""SELECT count(*) AS count FROM pg_class
        WHERE relnamespace=current_schema()::regnamespace AND relrowsecurity AND relname=ANY(%s)""",
                                   (list(CHECKPOINT_TABLES),)).fetchone()["count"]
    if protected != len(CHECKPOINT_TABLES):
        return False
    version = connection.execute("SELECT max(v) AS version FROM checkpoint_migrations").fetchone()["version"]
    return version == len(PostgresSaver.MIGRATIONS) - 1


class ClaimCheckpointer(PostgresSaver):
    """Serialize saver operations on one connection and fence them inside its transaction."""

    def __init__(self, connection, run_id, token):
        super().__init__(connection)
        self.run_id = str(run_id)
        self.token = token
        self.transaction_lock = Lock()

    def _valid_lease(self):
        row = self.conn.execute("""SELECT 1 FROM v1_runs WHERE run_id=%s AND claim_token=%s
                                   AND lease_until > clock_timestamp() AND snapshot->>'status'='running'""",
                                (self.run_id, self.token)).fetchone()
        if row is None:
            raise LostClaim()

    @contextmanager
    def _fenced(self, config):
        if not config or config.get("configurable", {}).get("thread_id") != self.run_id:
            raise ValueError("Checkpoint thread does not match the claimed run")
        with self.transaction_lock, self.conn.transaction():
            self.conn.execute("SELECT 1 FROM v1_runs WHERE run_id=%s FOR UPDATE", (self.run_id,)).fetchone()
            self._valid_lease()
            yield
            self._valid_lease()

    def get_tuple(self, config):
        with self._fenced(config):
            return super().get_tuple(config)

    def list(self, config, **kwargs):
        if kwargs.get("before") and kwargs["before"].get("configurable", {}).get("thread_id") != self.run_id:
            raise ValueError("Checkpoint cursor does not match the claimed run")
        with self._fenced(config):
            rows = list(super().list(config, **kwargs))
        yield from rows

    def put(self, config, checkpoint, metadata, new_versions):
        with self._fenced(config):
            return super().put(config, checkpoint, metadata, new_versions)

    def put_writes(self, config, writes, task_id, task_path=""):
        with self._fenced(config):
            return super().put_writes(config, writes, task_id, task_path)
