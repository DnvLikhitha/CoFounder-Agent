"""
api/routes/run.py — POST /api/run and GET /api/run/{run_id} and related endpoints
"""
import asyncio
import uuid
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional
from loguru import logger

from backend.context import RunContext
from backend.orchestrator import StartupOrchestrator
from backend.db.session import (
    save_run,
    update_run_status,
    save_agent_output,
    get_run,
    get_agent_outputs,
    get_user_runs,
    get_recent_runs,
    delete_run,
)

router = APIRouter()

# In-memory storage for active run contexts (for SSE streaming)
active_runs: dict[str, RunContext] = {}
run_events: dict[str, list] = {}  # run_id -> list of events


class RunCreateRequest(BaseModel):
    problem: str = Field(..., min_length=10, max_length=500)
    domain: Optional[str] = None
    geography: Optional[str] = None


async def run_pipeline_background(run_id: str, problem: str, domain: str, geography: str):
    """Background task that runs the pipeline and persists results."""
    orchestrator = StartupOrchestrator()

    # Initialize event queue for SSE
    run_events[run_id] = []

    async def event_callback(event_type: str, data: dict):
        event = {"event": event_type, "data": data}
        run_events[run_id].append(event)

        # Save agent outputs to DB as they complete
        if event_type == "agent_done":
            agent_name = data.get("agent", "")
            layer = data.get("layer", 0)
            output = data.get("output", {})
            latency = data.get("latency_ms", 0)
            await save_agent_output(run_id, agent_name, layer, output, latency)

        # Update run status on completion/error
        if event_type == "pipeline_complete":
            await update_run_status(run_id, "completed")
        elif event_type == "pipeline_error":
            await update_run_status(run_id, "failed", error=data.get("error", "Unknown error"))

    try:
        ctx = await orchestrator.run(
            problem=problem,
            run_id=run_id,
            domain=domain,
            geography=geography,
            event_callback=event_callback,
        )
        active_runs[run_id] = ctx

        # Update agent statuses
        await update_run_status(run_id, "completed", agent_statuses=ctx.status)

    except Exception as e:
        logger.error(f"Pipeline failed for {run_id}: {e}")
        await update_run_status(run_id, "failed", error=str(e))
        run_events[run_id].append({
            "event": "pipeline_error",
            "data": {"run_id": run_id, "error": str(e)}
        })


@router.post("/api/run")
async def create_run(request: RunCreateRequest, background_tasks: BackgroundTasks):
    """Start a new AI pipeline run."""
    run_id = str(uuid.uuid4())

    # Save run to DB
    await save_run(run_id, request.problem, request.domain, request.geography)

    # Start pipeline in background
    background_tasks.add_task(
        run_pipeline_background,
        run_id, request.problem, request.domain, request.geography
    )

    logger.info(f"🚀 Started new run: {run_id}")
    return {"run_id": run_id, "status": "started"}


@router.get("/api/run/{run_id}")
async def get_run_status(run_id: str):
    """Get run status and all agent outputs."""
    run = await get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    outputs = await get_agent_outputs(run_id)

    return {
        "run": run,
        "agent_outputs": outputs,
        "context": active_runs.get(run_id).__dict__ if run_id in active_runs else None,
    }


@router.delete("/api/run/{run_id}")
async def delete_run_endpoint(run_id: str):
    """Delete a run and all associated data."""
    await delete_run(run_id)
    active_runs.pop(run_id, None)
    run_events.pop(run_id, None)
    return {"message": "Run deleted"}


@router.get("/api/runs")
async def list_runs():
    """List recent runs (demo: no auth required for now)."""
    # In production, get user_id from JWT token
    runs = await get_recent_runs(limit=25)
    return {"runs": runs}


@router.get("/api/run/{run_id}/result")
async def get_run_result(run_id: str):
    """
    Return a flat dict of all agent outputs for a completed run.
    Used by the frontend SSE onerror recovery handler.
    """
    # First try in-memory context (most up-to-date, includes fallbacks)
    ctx = active_runs.get(run_id)
    if ctx:
        result = {}
        ctx_fields = [
            "problem_refined", "startup_idea", "market_research",
            "competitor_analysis", "customer_personas", "product_design",
            "mvp_roadmap", "business_model", "pricing_strategy",
            "financial_projections", "risk_register", "tech_architecture",
            "database_schema", "security_compliance", "pitch_deck",
            "executive_summary",
        ]
        for field in ctx_fields:
            val = getattr(ctx, field, None)
            if val:
                result[field] = val
        return result

    # Fall back to DB agent outputs
    outputs = await get_agent_outputs(run_id)
    if not outputs:
        raise HTTPException(status_code=404, detail="No results found for this run")

    key_map = {
        "Agent0_Refiner": "problem_refined",
        "Agent1_IdeaGenerator": "startup_idea",
        "Agent2_MarketResearch": "market_research",
        "Agent3_Competitors": "competitor_analysis",
        "Agent4_Personas": "customer_personas",
        "Agent5_ProductDesigner": "product_design",
        "Agent6_MVPRoadmap": "mvp_roadmap",
        "Agent7_BusinessModel": "business_model",
        "Agent8_Pricing": "pricing_strategy",
        "Agent9_Financials": "financial_projections",
        "Agent10_RiskAnalyst": "risk_register",
        "Agent11_TechArchitecture": "tech_architecture",
        "Agent12_DatabaseSchema": "database_schema",
        "Agent13_Security": "security_compliance",
        "Agent14_PitchDeck": "pitch_deck",
        "Agent15_ExecutiveSummary": "executive_summary",
    }

    result = {}
    for out in outputs:
        key = key_map.get(out.get("agent_name", ""), "")
        if key and out.get("output_data"):
            result[key] = out["output_data"]
    return result
