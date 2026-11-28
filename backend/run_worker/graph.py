"""The versioned 16-agent StateGraph and its durable worker adapter."""
from contextlib import contextmanager
from functools import partial
import json
from pathlib import Path
from threading import Event, Thread
from typing import Annotated, TypedDict
from collections.abc import Callable

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from langsmith import tracing_context

from backend.config import settings
from backend.run_worker.checkpoints import ClaimCheckpointer, checkpoint_schema_ready
from backend.run_worker.ledger import BudgetExceeded
from backend.run_worker.provider_call import ClaimCalls
from backend.run_worker.store import LostClaim
from backend.run_worker.workflow import (
    GRAPH_VERSION, LIVE_STEPS, InvalidOutput, PartialOutput, ProviderFailure, ProviderTimeout, check_graph,
)

PRICING = "pricing_strategy"
FINANCIALS = "financial_projections"
REVIEW = "pricing_review"


class FounderInput(TypedDict):
    problem: str
    domain: str | None
    geography: str | None


class StepOutcome(TypedDict):
    status: str
    error: dict | None
    artifact: dict | None
    required: dict[str, str]
    optional: dict[str, str]
    research_artifact_id: str | None
    assumptions_artifact_id: str | None


def merge_outcomes(left: dict[str, StepOutcome], right: dict[str, StepOutcome]) -> dict[str, StepOutcome]:
    if any(left[step] != right[step] for step in left.keys() & right.keys()):
        raise ValueError("Conflicting graph step outcomes")
    merged = left | right
    return {step: merged[step] for step in sorted(merged)}


class RunGraphState(TypedDict, total=False):
    run_id: str
    input: FounderInput
    workflow_version: str
    prompt_version: str
    model_profile: str | None
    provider_mode: str
    outcomes: Annotated[dict[str, StepOutcome], merge_outcomes]
    review_pricing: bool
    review: dict


def route_after_pricing(state: RunGraphState):
    if state["review_pricing"] and state["outcomes"][PRICING]["status"] == "succeeded":
        return REVIEW
    return FINANCIALS


def review_pricing(state: RunGraphState):
    # The node restarts from this point on resume. It only reads a committed reference.
    artifact = state["outcomes"][PRICING]["artifact"]
    response = interrupt({"step_id": PRICING, "artifact_id": artifact["artifact_id"]})
    if response != "approve":
        raise ValueError("Unsupported internal pricing review decision")
    return {"review": {"step_id": PRICING, "artifact_id": artifact["artifact_id"], "decision": response}}


def build_graph(run_node: Callable, checkpointer=None, *, steps=LIVE_STEPS):
    dependencies = {name: tuple(dict.fromkeys(spec.required + spec.optional)) for name, spec in steps.items()}
    check_graph(dependencies)
    # Pricing is the last prerequisite for financials, including all alternate ancestors.
    # Keep the pricing review conditional edge as the single trigger for financials.
    ancestors = set()
    pending = list(dependencies[PRICING])
    while pending:
        dependency = pending.pop()
        if dependency not in ancestors:
            ancestors.add(dependency)
            pending.extend(dependencies[dependency])
    if PRICING not in dependencies[FINANCIALS] or set(dependencies[FINANCIALS]) - ancestors - {PRICING}:
        raise ValueError("Financial prerequisites must precede the pricing checkpoint")

    graph = StateGraph(RunGraphState)
    for step in steps:
        graph.add_node(step, partial(run_node, step))
    graph.add_node(REVIEW, review_pricing)
    for step, upstream in dependencies.items():
        if step != FINANCIALS:
            graph.add_edge(list(upstream) if upstream else START, step)
    graph.add_conditional_edges(PRICING, route_after_pricing, {REVIEW: REVIEW, FINANCIALS: FINANCIALS})
    graph.add_edge(REVIEW, FINANCIALS)
    upstream_nodes = {key for deps in dependencies.values() for key in deps}
    for leaf in steps.keys() - upstream_nodes:
        graph.add_edge(leaf, END)
    return graph.compile(checkpointer=checkpointer)


def demo_provider(step_id, body, upstream):
    fixtures = json.loads(Path(__file__).with_name("demo_outputs.json").read_text(encoding="utf-8"))
    sample = fixtures[step_id]
    if step_id == "customer_personas":
        return sample["personas"]
    if step_id == "pitch_deck":
        return {"slides": sample}
    if step_id == "market_research":
        sample["tool_evidence"] = {"serpapi_sources": ["https://example.org/demo-research"]}
    return sample


@contextmanager
def maintain_lease(store, claim, seconds, mode, calls):
    store.renew(*claim, seconds)
    stop = Event()
    errors = []

    def heartbeat():
        while not stop.wait(seconds / 3):
            try:
                store.renew(*claim, seconds)
                if mode is not None:
                    store.heartbeat(mode)
            except Exception:
                errors.append(LostClaim())
                calls.cancel()
                return

    thread = Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()
        if errors:
            raise errors[0] from None


def run_agent_node(step_id, state, *, database, claim, invoke_provider, calls):
    try:
        inputs = database.begin_step(*claim, step_id)
        # A committed terminal outcome can outlive the corresponding checkpoint write.
        if inputs is not None:
            try:
                output = invoke_provider(step_id, *inputs)
                is_partial = isinstance(output, PartialOutput)
                database.complete_step(*claim, step_id, output.content if is_partial else output, partial=is_partial)
            except InvalidOutput:
                database.fail(*claim, step_id, invalid_output=True)
            except ProviderTimeout:
                database.fail(*claim, step_id, timed_out=True)
            except BudgetExceeded:
                database.fail(*claim, step_id, budget_exceeded=True)
            except ProviderFailure:
                database.fail(*claim, step_id)
        return {"outcomes": {step_id: database.graph_step_outcome(*claim, step_id)}}
    except LostClaim:
        calls.cancel()
        raise
    except Exception:
        calls.cancel()
        raise RuntimeError("Graph node interrupted") from None


def execute_graph(store, claim, config, invoke_provider, calls, *, lease_seconds, heartbeat_mode, review=False):
    run_id, token = claim
    identity = {
        "run_id": run_id, "input": config["input"], "workflow_version": GRAPH_VERSION,
        "prompt_version": config["prompt_version"], "model_profile": config["model_profile"],
        "provider_mode": config["graph_mode"],
    }
    # A graph is compiled against its frozen manifest. A different topology needs a new version.
    expected = {step: list(spec.required) for step, spec in LIVE_STEPS.items()}
    if {step["step_id"]: step["depends_on"] for step in config["manifest"]["steps"]} != expected:
        raise ValueError("Pinned graph manifest does not match the registered graph")
    thread_config = {"configurable": {"thread_id": run_id}, "max_concurrency": settings.v1_step_concurrency}
    node = partial(run_agent_node, database=store, claim=claim, invoke_provider=invoke_provider, calls=calls)
    with maintain_lease(store, claim, lease_seconds, heartbeat_mode, calls), \
         store.connect(autocommit=True, prepare_threshold=0) as connection, tracing_context(enabled=False):
        if not checkpoint_schema_ready(connection):
            raise ValueError("Checkpoint schema is not ready")
        graph = build_graph(node, ClaimCheckpointer(connection, run_id, token))
        snapshot = graph.get_state(thread_config)
        if snapshot.created_at is None:
            result = graph.invoke({**identity, "outcomes": {}, "review_pricing": review},
                                  thread_config, durability="sync", version="v2")
            interrupts = result.interrupts
        else:
            # The initial input checkpoint can predate materialization of the state channels.
            if "run_id" in snapshot.values and any(snapshot.values.get(key) != value for key, value in identity.items()):
                raise ValueError("Checkpoint identity does not match the claimed run")
            interrupts = snapshot.interrupts
            if interrupts and config["graph_resume_id"] == interrupts[0].id:
                result = graph.invoke(Command(resume={interrupts[0].id: "approve"}), thread_config,
                                      durability="sync", version="v2")
                interrupts = result.interrupts
            elif snapshot.next and not interrupts:
                interrupts = graph.invoke(None, thread_config, durability="sync", version="v2").interrupts
    # The last checkpoint may already be durable when this application transaction is retried.
    if interrupts:
        store.park_graph(run_id, token, interrupts[0].id)
    else:
        store.finish(run_id, token)
