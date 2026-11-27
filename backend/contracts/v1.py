"""Source of truth for the proposed v1 REST and SSE payloads."""
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

EventId = Annotated[int, Field(ge=0, le=9007199254740991)]
Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunStatus(str, Enum):
    queued = "queued"
    running = "running"
    awaiting_review = "awaiting_review"
    succeeded = "succeeded"
    partial = "partial"
    failed = "failed"


class StepStatus(str, Enum):
    queued = "queued"
    running = "running"
    awaiting_review = "awaiting_review"
    succeeded = "succeeded"
    partial = "partial"
    failed = "failed"
    skipped = "skipped"


class RunInput(Contract):
    problem: str = Field(min_length=10, max_length=500)
    domain: str | None = Field(default=None, max_length=100)
    geography: str | None = Field(default=None, max_length=100)


class ErrorDetail(Contract):
    code: str
    message: str
    retryable: bool


class ErrorResponse(Contract):
    error: ErrorDetail


class StepDefinition(Contract):
    step_id: Identifier
    label: str
    phase: str
    order: int = Field(ge=0)
    depends_on: list[Identifier]
    required: bool
    artifact_kinds: list[str]


class StepManifest(Contract):
    version: str
    steps: list[StepDefinition]


class StepState(Contract):
    step_id: Identifier
    status: StepStatus
    attempt: int = Field(ge=0)
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    error: ErrorDetail | None


class ArtifactReference(Contract):
    artifact_id: Identifier
    step_id: Identifier
    kind: str
    title: str
    media_type: Literal["application/json", "text/markdown", "text/plain"]
    quality: Literal["complete", "partial", "fallback"]
    created_at: AwareDatetime
    href: str = Field(pattern=r"^/api/v1/runs/[^/]+/artifacts/[^/]+$")


class Artifact(Contract):
    run_id: UUID
    reference: ArtifactReference
    content: JsonValue


class EvaluationResult(Contract):
    evaluation_id: Identifier
    step_id: Identifier | None
    artifact_id: Identifier | None
    evaluator: str
    evaluator_version: str
    outcome: Literal["passed", "failed", "needs_review", "not_evaluated"]
    score: float | None = Field(ge=0, le=1)
    reasons: list[str]
    created_at: AwareDatetime


class ReviewRequest(Contract):
    review_id: Identifier
    step_id: Identifier | None
    artifact_ids: list[Identifier]
    prompt: str
    created_at: AwareDatetime


class ReviewDecision(Contract):
    decision_id: UUID
    decision: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=2000)


class ReviewReceipt(Contract):
    run_id: UUID
    review_id: Identifier
    decision: ReviewDecision
    decided_at: AwareDatetime
    event_id: EventId


class RunState(Contract):
    status: RunStatus
    updated_at: AwareDatetime
    completed_at: AwareDatetime | None
    error: ErrorDetail | None


class RunSummary(RunState):
    run_id: UUID
    input: RunInput
    created_at: AwareDatetime


class RunSnapshot(RunSummary):
    contract_version: Literal["1.0"]
    last_event_id: EventId
    manifest: StepManifest
    steps: list[StepState]
    artifacts: list[ArtifactReference]
    evaluations: list[EvaluationResult]
    pending_review: ReviewRequest | None


class HistoryPage(Contract):
    runs: list[RunSummary]
    next_cursor: str | None


class ArtifactList(Contract):
    artifacts: list[ArtifactReference]


class EventBase(Contract):
    contract_version: Literal["1.0"]
    run_id: UUID
    event_id: Annotated[int, Field(ge=1, le=9007199254740991)]
    occurred_at: AwareDatetime


class RunUpdated(EventBase):
    type: Literal["run.updated"]
    data: RunState


class StepUpdated(EventBase):
    type: Literal["step.updated"]
    data: StepState


class ArtifactCreated(EventBase):
    type: Literal["artifact.created"]
    data: ArtifactReference


class EvaluationCompleted(EventBase):
    type: Literal["evaluation.completed"]
    data: EvaluationResult


class ReviewRequested(EventBase):
    type: Literal["review.requested"]
    data: ReviewRequest


class ReviewDecided(EventBase):
    type: Literal["review.decided"]
    data: ReviewReceipt


RunEvent = Annotated[
    RunUpdated | StepUpdated | ArtifactCreated | EvaluationCompleted | ReviewRequested | ReviewDecided,
    Field(discriminator="type"),
]
EVENT_ADAPTER = TypeAdapter(RunEvent)
