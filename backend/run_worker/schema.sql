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
