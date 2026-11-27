"""Run with python -m backend.contracts.tool [--check]."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from backend.contracts.rest import app
from backend.contracts.v1 import (
    Artifact, ArtifactList, ErrorResponse, EVENT_ADAPTER, HistoryPage,
    ReviewDecision, ReviewReceipt, RunInput, RunSnapshot,
)

ROOT = Path(__file__).resolve().parents[2] / "shared" / "contracts"
TERMINAL = {"succeeded", "partial", "failed"}


def encode(value):
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def upsert(items, value, key):
    for index, item in enumerate(items):
        if item[key] == value[key]:
            items[index] = value
            return
    items.append(value)


def replay(snapshot, events):
    """Reference reducer for fixtures; duplicates are harmless."""
    state = deepcopy(snapshot)
    for event in events:
        EVENT_ADAPTER.validate_python(event)
        assert event["run_id"] == state["run_id"], "Wrong run"
        if event["event_id"] <= state["last_event_id"]:
            continue
        assert event["event_id"] == state["last_event_id"] + 1, "Event gap"
        assert state["status"] not in TERMINAL, "Event after terminal state"
        data = deepcopy(event["data"])
        kind = event["type"]
        if kind == "run.updated":
            state.update(data)
        elif kind == "step.updated":
            assert data["step_id"] in {s["step_id"] for s in state["manifest"]["steps"]}
            upsert(state["steps"], data, "step_id")
        elif kind == "artifact.created":
            upsert(state["artifacts"], data, "artifact_id")
        elif kind == "evaluation.completed":
            upsert(state["evaluations"], data, "evaluation_id")
        elif kind == "review.requested":
            assert state["pending_review"] is None
            state["pending_review"] = data
        elif kind == "review.decided":
            assert state["pending_review"]["review_id"] == data["review_id"]
            assert data["event_id"] == event["event_id"]
            assert data["run_id"] == event["run_id"]
            state["pending_review"] = None
        state["last_event_id"] = event["event_id"]
        state["updated_at"] = event["occurred_at"]
    return state


def validate_fixture(directory):
    initial = json.loads((directory / "snapshot.json").read_text(encoding="utf-8"))
    final = json.loads((directory / "final.json").read_text(encoding="utf-8"))
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    RunSnapshot.model_validate(initial)
    RunSnapshot.model_validate(final)
    assert [e["event_id"] for e in events] == list(range(initial["last_event_id"] + 1, final["last_event_id"] + 1))
    assert replay(initial, events) == final, "Replay differs from final snapshot"
    # Every snapshot boundary must resume correctly, including duplicate delivery.
    for boundary in range(len(events) + 1):
        middle = replay(initial, events[:boundary])
        assert replay(middle, events[max(0, boundary - 1):]) == final
    definitions = final["manifest"]["steps"]
    step_ids = {s["step_id"] for s in definitions}
    assert len(step_ids) == len(definitions)
    assert {s["step_id"] for s in final["steps"]} == step_ids
    for step in definitions:
        assert set(step["depends_on"]) <= step_ids - {step["step_id"]}
    artifacts = json.loads((directory / "artifacts.json").read_text(encoding="utf-8"))
    assert [a["reference"] for a in artifacts] == final["artifacts"]
    artifact_ids = {a["artifact_id"] for a in final["artifacts"]}
    for artifact in artifacts:
        Artifact.model_validate(artifact)
        reference = artifact["reference"]
        assert artifact["run_id"] == final["run_id"]
        assert reference["step_id"] in step_ids
        assert reference["href"] == f'/api/v1/runs/{final["run_id"]}/artifacts/{reference["artifact_id"]}'
    for evaluation in final["evaluations"]:
        assert evaluation["step_id"] is None or evaluation["step_id"] in step_ids
        assert evaluation["artifact_id"] is None or evaluation["artifact_id"] in artifact_ids
    assert final["pending_review"] is None
    assert final["completed_at"] is not None
    assert final["status"] == directory.name
    if final["status"] == "succeeded":
        assert all(s["status"] == "succeeded" for s in final["steps"])
        assert all(a["quality"] == "complete" for a in final["artifacts"])
    else:
        assert final["artifacts"]
        assert any(s["status"] in {"failed", "partial", "skipped"} for s in final["steps"])
    return "".join(
        f'id: {event["event_id"]}\nevent: {event["type"]}\ndata: {json.dumps(event, separators=(",", ":"))}\n\n'
        for event in events
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate without writing; fail on schema or SSE drift")
    args = parser.parse_args()
    schema = EVENT_ADAPTER.json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    outputs = {ROOT / "openapi.json": encode(app.openapi()), ROOT / "sse.schema.json": encode(schema)}
    for directory in sorted((ROOT / "fixtures").iterdir()):
        if directory.is_dir():
            outputs[directory / "events.sse"] = validate_fixture(directory)
    examples = json.loads((ROOT / "examples.json").read_text(encoding="utf-8"))
    models = {"start_request": RunInput, "start_response": RunSnapshot,
              "history_response": HistoryPage, "artifact_list": ArtifactList,
              "artifact_response": Artifact, "review_request": ReviewDecision,
              "review_response": ReviewReceipt, "error_response": ErrorResponse}
    assert examples.keys() == models.keys()
    for name, model in models.items():
        model.model_validate(examples[name])
    for path, content in outputs.items():
        if args.check:
            assert path.read_text(encoding="utf-8") == content, f"Regenerate {path}"
        else:
            path.write_text(content, encoding="utf-8", newline="\n")
    print("Validated examples, both replay fixtures, every reconnect boundary, and schema/SSE consistency.")


if __name__ == "__main__":
    main()
