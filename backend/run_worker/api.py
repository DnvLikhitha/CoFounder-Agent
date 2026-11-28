"""Mounted v1 API with authenticated, owner-scoped database reads."""
import asyncio
from datetime import datetime
import json
import time
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
import psycopg
from starlette.concurrency import run_in_threadpool

from backend.config import settings
from backend.context import RunContext
from backend.contracts.rest import EVENT_RESPONSES, EXPORT_RESPONSES, HistoryCursor, IdempotencyKey, error_responses
from backend.contracts.v1 import (
    Artifact, ArtifactList, EVENT_ADAPTER, EventId, HistoryPage, Identifier, ReviewDecision, ReviewReceipt,
    RunInput, RunSnapshot,
)
from backend.run_worker.auth import Owner, owner
from backend.safe_logging import SafeRequests
from backend.run_worker.prompts_v1 import apply_artifact
from backend.run_worker.store import Store, StoreError, TERMINAL, latest_artifacts
from backend.run_worker.workflow import FAKE_VERSIONS, REVIEWED_VERSION

app = FastAPI(title="CoFounder-Agent Run Contract", version="1.0.0")
app.add_middleware(SafeRequests, private=True)


def store():
    return Store(settings.database_url)


OwnerDependency = Annotated[Owner, Depends(owner)]
StoreDependency = Annotated[Store, Depends(store)]


@app.exception_handler(StoreError)
async def store_error(request, exc):
    headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else None
    return JSONResponse(status_code=exc.status, headers=headers, content={"error": {
        "code": exc.code, "message": str(exc), "retryable": exc.status == 503}})


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse(status_code=422, content={"error": {
        "code": "validation_error", "message": "Invalid request", "retryable": False}})


@app.exception_handler(psycopg.Error)
async def database_error(request, exc):
    return JSONResponse(status_code=503, content={"error": {
        "code": "service_unavailable", "message": "Database temporarily unavailable", "retryable": True}})


@app.post("/runs", response_model=RunSnapshot, status_code=202, responses=error_responses(409))
def submit(body: RunInput, user: OwnerDependency, database: StoreDependency,
           idempotency_key: IdempotencyKey = None):
    try:
        mode = settings.require_v1_provider_mode()
    except ValueError as exc:
        raise StoreError(503, "service_unavailable", str(exc)) from None
    return database.submit(
        user.subject, idempotency_key, body.model_dump(mode="json"), version=REVIEWED_VERSION, graph_mode=mode,
        token_limit=settings.v1_run_token_limit, cost_limit=settings.v1_run_cost_limit_nanousd,
        require_review=mode == "live" and settings.v1_require_founder_review,
        pricing_review=settings.v1_require_pricing_review,
        llm_evaluation=settings.v1_llm_evaluation,
    )


@app.get("/runs", response_model=HistoryPage, responses=error_responses())
def history(user: OwnerDependency, database: StoreDependency,
            limit: Annotated[int, Query(ge=1, le=100)] = 25,
            cursor: HistoryCursor = None):
    return database.history(user.subject, limit, cursor)


@app.get("/runs/{run_id}", response_model=RunSnapshot, responses=error_responses(404))
def snapshot(run_id: UUID, user: OwnerDependency, database: StoreDependency):
    return database.snapshot(user.subject, run_id)


@app.get("/runs/{run_id}/artifacts", response_model=ArtifactList, responses=error_responses(404))
def artifacts(run_id: UUID, user: OwnerDependency, database: StoreDependency):
    return {"artifacts": database.snapshot(user.subject, run_id)["artifacts"]}


@app.get("/runs/{run_id}/artifacts/{artifact_id}", response_model=Artifact, responses=error_responses(404))
def artifact(run_id: UUID, artifact_id: Identifier, user: OwnerDependency, database: StoreDependency):
    return database.artifact(user.subject, run_id, artifact_id)


@app.get("/runs/{run_id}/events", response_class=Response, responses=EVENT_RESPONSES)
async def events(request: Request, run_id: UUID, user: OwnerDependency, database: StoreDependency,
                 after: EventId = 0,
                 last_event_id: Annotated[EventId | None, Header(alias="Last-Event-ID")] = None):
    cursor = after if last_event_id is None else last_event_id
    initial = await run_in_threadpool(database.snapshot, user.subject, run_id)
    if cursor > initial["last_event_id"]:
        raise StoreError(409, "event_cursor_ahead", "Cursor is ahead of the run")
    if cursor == initial["last_event_id"] and initial["status"] in TERMINAL:
        return Response(status_code=204)

    async def stream():
        nonlocal cursor
        heartbeat = time.monotonic()
        while time.time() < user.expires_at and not await request.is_disconnected():
            try:
                batch = await run_in_threadpool(database.events, user.subject, run_id, cursor)
            except psycopg.Error:
                return  # Reconnect from the persisted cursor after a transient outage.
            for event in batch:
                if time.time() >= user.expires_at:
                    return
                # Use the same datetime serialization as REST, including for already persisted events.
                payload = EVENT_ADAPTER.validate_python(event).model_dump(mode="json")
                yield f'id: {event["event_id"]}\nevent: {event["type"]}\ndata: {json.dumps(payload)}\n\n'
                cursor = event["event_id"]
                if event["type"] == "run.updated" and event["data"]["status"] in TERMINAL:
                    return
            if time.time() >= user.expires_at:
                return
            if time.monotonic() - heartbeat >= 15:
                yield ": keepalive\n\n"
                heartbeat = time.monotonic()
            if not batch:
                await asyncio.sleep(0.2)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no"})


@app.post("/runs/{run_id}/reviews/{review_id}/decisions",
          response_model=ReviewReceipt, responses=error_responses(404, 409))
def review(run_id: UUID, review_id: Identifier, body: ReviewDecision, user: OwnerDependency, database: StoreDependency):
    return database.decide_review(user.subject, run_id, review_id, body.model_dump(mode="json"))


@app.get("/runs/{run_id}/exports/{format}", response_class=Response, responses=EXPORT_RESPONSES)
async def export(run_id: UUID, format: Literal["pdf", "markdown", "pptx"],
                 user: OwnerDependency, database: StoreDependency):
    state = await run_in_threadpool(database.snapshot, user.subject, run_id)
    if state["status"] not in {"succeeded", "partial"}:
        raise StoreError(409, "state_conflict", "Run has no exportable result")
    context = RunContext(run_id=str(run_id), problem_raw=state["input"]["problem"],
                         domain=state["input"]["domain"], geography=state["input"]["geography"])
    context.created_at = datetime.fromisoformat(state["created_at"])
    context.completed_at = datetime.fromisoformat(state["completed_at"])
    context.status = {step["step_id"]: step["status"] for step in state["steps"]}
    references = latest_artifacts(state).values() if state["manifest"]["version"] == REVIEWED_VERSION else state["artifacts"]
    for reference in references:
        if state["manifest"]["version"] == REVIEWED_VERSION and context.status[reference["step_id"]] not in {"succeeded", "partial"}:
            continue
        body = await run_in_threadpool(database.artifact, user.subject, run_id, reference["artifact_id"])
        apply_artifact(context, reference["kind"], body["content"])
    labels = {step["step_id"]: step["label"] for step in state["manifest"]["steps"]}
    missing = [labels[step["step_id"]] for step in state["steps"] if step["status"] in {"skipped", "failed"}]
    degraded = [labels[step["step_id"]] for step in state["steps"] if step["status"] == "partial"]
    status = "Partial results" if state["status"] == "partial" else "Succeeded"
    version = state["manifest"]["version"]
    is_demo = await run_in_threadpool(database.is_demo, user.subject, run_id, version)
    notice = f"Fake-provider demonstration. {status}." if is_demo else f"{status}."
    if missing:
        notice += " Missing sections: " + ", ".join(missing) + "."
    if degraded:
        notice += " Incomplete sections: " + ", ".join(degraded) + "."

    if version in FAKE_VERSIONS:
        highlights = []
        if model := context.business_model.get("model"):
            highlights.append(f"Business model: {model}.")
        for tier in context.pricing_strategy.get("tiers", []):
            # Older fake runs used `name`; the report generators expect `tier_name`.
            tier_name = tier.setdefault("tier_name", tier.get("name", "Tier"))
            highlights.append(f'{tier_name} pricing: ${tier["price_monthly_usd"]}/month.')
        if month := context.financial_projections.get("breakeven_month"):
            highlights.append(f"Break-even month: {month}.")
        if context.risk_register:
            highlights.append(f'Risks recorded: {len(context.risk_register["risks"])}.')
        context.startup_idea = {"startup_name": "Fake workflow result", "tagline": status}
        context.executive_summary = {"executive_summary": " ".join(highlights)}
        context.pitch_deck = {"slides": [{"title": "Workflow results", "bullet_points": highlights}]}
    if format == "markdown":
        from backend.export.markdown_writer import generate_markdown
        content, media = (await generate_markdown(context, notice=notice)).encode(), "text/markdown"
    elif format == "pdf":
        from backend.export.pdf_generator import generate_pdf
        content, media = await generate_pdf(context, notice=notice), "application/pdf"
    else:
        from backend.export.pptx_generator import generate_pptx
        content = await run_in_threadpool(generate_pptx, context, notice=notice)
        media = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    extension = "md" if format == "markdown" else format
    return Response(content, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="run-{run_id}.{extension}"'})
