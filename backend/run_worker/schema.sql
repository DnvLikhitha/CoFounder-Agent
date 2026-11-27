CREATE TABLE IF NOT EXISTS v1_runs (
    run_id uuid PRIMARY KEY,
    owner_id text NOT NULL,
    submission_key text NOT NULL,
    input jsonb NOT NULL,
    initial_snapshot jsonb NOT NULL,
    snapshot jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    claim_token uuid,
    lease_until timestamptz,
    UNIQUE (owner_id, submission_key)
);
CREATE INDEX IF NOT EXISTS v1_runs_queue ON v1_runs ((snapshot->>'status'), created_at);
CREATE INDEX IF NOT EXISTS v1_runs_owner ON v1_runs (owner_id, created_at DESC, run_id DESC);
CREATE TABLE IF NOT EXISTS v1_artifacts (
    run_id uuid NOT NULL REFERENCES v1_runs(run_id),
    artifact_id text NOT NULL,
    body jsonb NOT NULL,
    PRIMARY KEY (run_id, artifact_id)
);
CREATE TABLE IF NOT EXISTS v1_events (
    run_id uuid NOT NULL REFERENCES v1_runs(run_id),
    event_id bigint NOT NULL CHECK (event_id BETWEEN 1 AND 9007199254740991),
    body jsonb NOT NULL,
    PRIMARY KEY (run_id, event_id)
);

ALTER TABLE v1_runs ADD COLUMN IF NOT EXISTS model_profile text;
ALTER TABLE v1_runs ADD COLUMN IF NOT EXISTS prompt_version text;
ALTER TABLE v1_runs ADD COLUMN IF NOT EXISTS token_limit bigint CHECK (token_limit > 0);
ALTER TABLE v1_runs ADD COLUMN IF NOT EXISTS cost_limit_nanousd bigint CHECK (cost_limit_nanousd > 0);
ALTER TABLE v1_runs ADD COLUMN IF NOT EXISTS require_review boolean NOT NULL DEFAULT false;
ALTER TABLE v1_runs ALTER COLUMN submission_key DROP NOT NULL;

-- Pre-ledger live runs start with a fixed budget for work after the migration.
UPDATE v1_runs SET model_profile='groq-gpt-oss-v1', prompt_version='startup-prompts-v1',
    token_limit=500000, cost_limit_nanousd=250000000
WHERE snapshot->'manifest'->>'version'='live-startup-v1' AND model_profile IS NULL
  AND snapshot->>'status' NOT IN ('succeeded', 'partial', 'failed');

CREATE TABLE IF NOT EXISTS v1_llm_attempts (
    attempt_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES v1_runs(run_id),
    step_id text NOT NULL,
    claim_token uuid NOT NULL,
    attempt_no integer NOT NULL CHECK (attempt_no > 0),
    step_attempt integer NOT NULL CHECK (step_attempt > 0),
    requested_model text NOT NULL,
    actual_model text,
    status text NOT NULL CHECK (status IN
        ('reserved', 'succeeded', 'unknown', 'transient', 'rate_limited', 'model_unavailable', 'rejected', 'failed')),
    reserved_prompt_tokens bigint NOT NULL CHECK (reserved_prompt_tokens > 0),
    reserved_completion_tokens bigint NOT NULL CHECK (reserved_completion_tokens > 0),
    reserved_cost_nanousd bigint NOT NULL CHECK (reserved_cost_nanousd > 0),
    prompt_tokens bigint CHECK (prompt_tokens >= 0),
    completion_tokens bigint CHECK (completion_tokens >= 0),
    charged_tokens bigint NOT NULL CHECK (charged_tokens >= 0),
    charged_cost_nanousd bigint NOT NULL CHECK (charged_cost_nanousd >= 0),
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    retry_at timestamptz,
    UNIQUE (run_id, step_id, attempt_no)
);

CREATE TABLE IF NOT EXISTS v1_review_decisions (
    run_id uuid NOT NULL REFERENCES v1_runs(run_id),
    review_id text NOT NULL,
    decision_id uuid NOT NULL,
    receipt jsonb NOT NULL,
    PRIMARY KEY (run_id, decision_id),
    UNIQUE (run_id, review_id)
);

CREATE TABLE IF NOT EXISTS v1_worker_heartbeats (
    mode text PRIMARY KEY,
    seen_at timestamptz NOT NULL
);

-- The trusted PostgreSQL runtime role owns these tables. Supabase Data API
-- roles have no direct access to runs, artifacts, review receipts, or usage.
DO $$
DECLARE
    relation text;
    role_name text;
BEGIN
    FOREACH relation IN ARRAY ARRAY['v1_runs', 'v1_artifacts', 'v1_events', 'v1_llm_attempts',
                                    'v1_review_decisions', 'v1_worker_heartbeats'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', relation);
        EXECUTE format('REVOKE ALL ON %I FROM PUBLIC', relation);
        FOR role_name IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated') LOOP
            EXECUTE format('REVOKE ALL ON %I FROM %I', relation, role_name);
        END LOOP;
    END LOOP;
END $$;
