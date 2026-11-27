"""Transactional accounting for requests that cross the worker process boundary."""
from dataclasses import dataclass
from uuid import uuid4

from backend.llm.profiles import MAX_ATTEMPTS
from backend.run_worker.workflow import ProviderFailure


class BudgetExceeded(ProviderFailure):
    pass


@dataclass(frozen=True)
class AttemptLedger:
    store: object
    run_id: str
    token: str
    step_id: str

    def history(self):
        with self.store._claimed(self.run_id, self.token) as (connection, _):
            return connection.execute(
                """SELECT status, requested_model,
                   GREATEST(0, COALESCE(EXTRACT(EPOCH FROM retry_at - clock_timestamp()), 0))::float AS wait
                   FROM v1_llm_attempts WHERE run_id=%s AND step_id=%s ORDER BY attempt_no""",
                (self.run_id, self.step_id)).fetchall()

    def reserve(self, model, prompt, completion):
        cost = model.cost(prompt, completion)
        with self.store._claimed(self.run_id, self.token) as (connection, snapshot):
            limits = connection.execute(
                "SELECT token_limit, cost_limit_nanousd FROM v1_runs WHERE run_id=%s", (self.run_id,)
            ).fetchone()
            totals = connection.execute(
                """SELECT COALESCE(SUM(charged_tokens),0) AS tokens,
                   COALESCE(SUM(charged_cost_nanousd),0) AS cost,
                   COUNT(*) FILTER (WHERE step_id=%s) AS attempts,
                   COUNT(*) FILTER (WHERE step_id=%s AND claim_token=%s) AS claim_attempts
                   FROM v1_llm_attempts WHERE run_id=%s""",
                (self.step_id, self.step_id, self.token, self.run_id)).fetchone()
            step = next(s for s in snapshot["steps"] if s["step_id"] == self.step_id)
            if step["status"] != "running" or totals["attempts"] >= MAX_ATTEMPTS:
                raise ProviderFailure()
            if (limits["token_limit"] is None or totals["tokens"] + prompt + completion > limits["token_limit"]
                    or totals["cost"] + cost > limits["cost_limit_nanousd"]):
                raise BudgetExceeded()
            if totals["claim_attempts"]:
                timestamp = connection.execute("SELECT clock_timestamp() AS time").fetchone()["time"].isoformat()
                step["attempt"] += 1
                self.store._emit(connection, snapshot, "step.updated", step, timestamp)
            reservation = uuid4()
            connection.execute(
                """INSERT INTO v1_llm_attempts (attempt_id, run_id, step_id, claim_token, attempt_no, step_attempt,
                   requested_model, status, reserved_prompt_tokens, reserved_completion_tokens, reserved_cost_nanousd,
                   charged_tokens, charged_cost_nanousd)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'reserved',%s,%s,%s,%s,%s)""",
                (reservation, self.run_id, self.step_id, self.token, totals["attempts"] + 1, step["attempt"],
                 model.name, prompt, completion, cost, prompt + completion, cost))
            return reservation

    def settle(self, attempt_id, status, *, actual_model=None, usage=None, cost=None, retry_delay=None):
        prompt, completion = usage if usage is not None else (None, None)
        tokens = prompt + completion if usage is not None else None
        with self.store._claimed(self.run_id, self.token) as (connection, _):
            updated = connection.execute(
                """UPDATE v1_llm_attempts SET status=%s, actual_model=%s, prompt_tokens=%s, completion_tokens=%s,
                   charged_tokens=COALESCE(%s, charged_tokens), charged_cost_nanousd=COALESCE(%s, charged_cost_nanousd),
                   finished_at=clock_timestamp(), retry_at=clock_timestamp() + %s * interval '1 second'
                   WHERE run_id=%s AND step_id=%s AND claim_token=%s AND attempt_id=%s AND status='reserved'""",
                (status, actual_model, prompt, completion, tokens, cost, retry_delay,
                 self.run_id, self.step_id, self.token, attempt_id))
            if not updated.rowcount:
                raise ProviderFailure()
