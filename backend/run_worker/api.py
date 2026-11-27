"""Mounted v1 API with authenticated, owner-scoped database reads."""
import asyncio
from dataclasses import dataclass
from datetime import datetime
import json
import time
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
import psycopg
from starlette.concurrency import run_in_threadpool

from backend.config import settings
from backend.context import RunContext
from backend.contracts.v1 import Artifact, ArtifactList, EventId, Identifier, RunInput, RunSnapshot
from backend.run_worker.store import Store, StoreError, TERMINAL

app = FastAPI(title="CoFounder-Agent v1 worker slice", version="1.0")
bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Owner:
    subject: str
    expires_at: float


def owner(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if len(settings.v1_jwt_secret) < 32:
        raise StoreError(503, "service_unavailable", "Authentication is not configured")
    if credentials is None:
        raise StoreError(401, "unauthorized", "Bearer token required")
    try:
        claims = jwt.decode(credentials.credentials, settings.v1_jwt_secret, algorithms=["HS256"],
                            audience=settings.v1_jwt_audience, issuer=settings.v1_jwt_issuer,
                            options={"require_exp": True, "require_sub": True, "require_aud": True, "require_iss": True})
        if not claims["sub"] or len(claims["sub"]) > 200:
            raise JWTError("Invalid subject")
        return Owner(claims["sub"], float(claims["exp"]))
    except (JWTError, ValueError, TypeError):
        raise StoreError(401, "unauthorized", "Invalid or expired bearer token") from None


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


@app.post("/runs", response_model=RunSnapshot, status_code=202)
def submit(body: RunInput, user: OwnerDependency, database: StoreDependency,
           idempotency_key: Annotated[str | None, Header(min_length=1, max_length=200)] = None):
    # An omitted key retains the merged contract's create-on-every-request behavior.
    return database.submit(user.subject, idempotency_key or str(uuid4()), body.model_dump(mode="json"))


@app.get("/runs/{run_id}", response_model=RunSnapshot)
def snapshot(run_id: UUID, user: OwnerDependency, database: StoreDependency):
    return database.snapshot(user.subject, run_id)


@app.get("/runs/{run_id}/artifacts", response_model=ArtifactList)
def artifacts(run_id: UUID, user: OwnerDependency, database: StoreDependency):
    return {"artifacts": database.snapshot(user.subject, run_id)["artifacts"]}


@app.get("/runs/{run_id}/artifacts/{artifact_id}", response_model=Artifact)
def artifact(run_id: UUID, artifact_id: Identifier, user: OwnerDependency, database: StoreDependency):
    return database.artifact(user.subject, run_id, artifact_id)


@app.get("/runs/{run_id}/events")
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
                yield f'id: {event["event_id"]}\nevent: {event["type"]}\ndata: {json.dumps(event)}\n\n'
                cursor = event["event_id"]
                if event["type"] == "run.updated" and event["data"]["status"] in TERMINAL:
                    return
            if time.monotonic() - heartbeat >= 15:
                yield ": keepalive\n\n"
                heartbeat = time.monotonic()
            if not batch:
                await asyncio.sleep(0.2)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/runs/{run_id}/exports/{format}")
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
    for reference in state["artifacts"]:
        body = await run_in_threadpool(database.artifact, user.subject, run_id, reference["artifact_id"])
        setattr(context, reference["kind"], body["content"])
    missing = [step["step_id"] for step in state["steps"] if step["status"] != "succeeded"]
    notice = "Fake-provider demonstration. " + ("Missing sections: " + ", ".join(missing) if missing else "All workflow steps completed.")
    context.startup_idea = {"startup_name": "Fake workflow result", "one_liner": notice}
    context.executive_summary = {"executive_summary": notice}
    if format == "markdown":
        from backend.export.markdown_writer import generate_markdown
        content, media = (await generate_markdown(context)).encode(), "text/markdown"
    elif format == "pdf":
        from backend.export.pdf_generator import generate_pdf
        content, media = await generate_pdf(context), "application/pdf"
    else:
        from backend.export.pptx_generator import generate_pptx
        content = await run_in_threadpool(generate_pptx, context)
        media = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    extension = "md" if format == "markdown" else format
    return Response(content, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="run-{run_id}.{extension}"'})
