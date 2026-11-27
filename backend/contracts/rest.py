"""Schema-only FastAPI application. Never mounted by backend.main."""
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Query
from fastapi.responses import Response
from fastapi.security import HTTPBearer

from backend.contracts.v1 import (
    Artifact, ArtifactList, ErrorResponse, EventId, HistoryPage, Identifier,
    ReviewDecision, ReviewReceipt, RunInput, RunSnapshot,
)

bearer = HTTPBearer(auto_error=False, scheme_name="BearerAuth", bearerFormat="JWT")
app = FastAPI(title="CoFounder-Agent Run Contract", version="1.0.0", dependencies=[Depends(bearer)])
IdempotencyKey = Annotated[str | None, Header(min_length=1, max_length=200)]
HistoryCursor = Annotated[str | None, Query(max_length=256)]
ERRORS = {
    code: {"model": ErrorResponse, "description": description}
    for code, description in {
        401: "Missing, invalid, or expired bearer token",
        404: "Run, artifact, or review not found",
        409: "State conflict or cursor ahead of run",
        410: "Replay cursor expired; fetch a fresh snapshot",
        422: "Invalid request",
        500: "Request processing failed",
        503: "Service temporarily unavailable",
    }.items()
}
ERRORS[401]["headers"] = {"WWW-Authenticate": {"schema": {"type": "string"}}}


def error_responses(*extra):
    return {code: ERRORS[code] for code in sorted({401, 422, 500, 503, *extra})}


EVENT_RESPONSES = {**error_responses(404, 409, 410), 204: {"description": "No more events for this terminal run"}, 200: {
    "description": "Ordered replay then live SSE. See sse.schema.json and README.md.",
    "content": {"text/event-stream": {"schema": {"type": "string"}}},
}}
EXPORT_RESPONSES = {**error_responses(404, 409), 200: {
    "description": "Attachment for a succeeded or partial run; media type follows format.",
    "headers": {"Content-Disposition": {"schema": {"type": "string"}}},
    "content": {
        media: {"schema": {"type": "string", "format": "binary"}}
        for media in ["application/pdf", "text/markdown", "application/vnd.openxmlformats-officedocument.presentationml.presentation"]
    },
}}


@app.post("/api/v1/runs", response_model=RunSnapshot, status_code=202, responses=error_responses(409))
def start_run(body: RunInput, idempotency_key: IdempotencyKey = None):
    raise NotImplementedError("Contract only")


@app.get("/api/v1/runs", response_model=HistoryPage, responses=error_responses())
def list_history(
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: HistoryCursor = None,
):
    raise NotImplementedError("Contract only")


@app.get("/api/v1/runs/{run_id}", response_model=RunSnapshot, responses=error_responses(404))
def get_snapshot(run_id: UUID):
    raise NotImplementedError("Contract only")


@app.get(
    "/api/v1/runs/{run_id}/events", response_class=Response,
    responses=EVENT_RESPONSES,
)
def replay_events(
    run_id: UUID,
    after: EventId = 0,
    last_event_id: Annotated[EventId | None, Header(alias="Last-Event-ID")] = None,
):
    raise NotImplementedError("Contract only")


@app.get("/api/v1/runs/{run_id}/artifacts", response_model=ArtifactList, responses=error_responses(404))
def list_artifacts(run_id: UUID):
    raise NotImplementedError("Contract only")


@app.get("/api/v1/runs/{run_id}/artifacts/{artifact_id}", response_model=Artifact, responses=error_responses(404))
def read_artifact(run_id: UUID, artifact_id: Identifier):
    raise NotImplementedError("Contract only")


@app.post("/api/v1/runs/{run_id}/reviews/{review_id}/decisions",
          response_model=ReviewReceipt, responses=error_responses(404, 409))
def submit_review(run_id: UUID, review_id: Identifier, body: ReviewDecision):
    raise NotImplementedError("Contract only")


@app.get(
    "/api/v1/runs/{run_id}/exports/{format}", response_class=Response,
    responses=EXPORT_RESPONSES,
)
def export_result(run_id: UUID, format: Literal["pdf", "markdown", "pptx"]):
    raise NotImplementedError("Contract only")
