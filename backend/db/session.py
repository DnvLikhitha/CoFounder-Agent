"""
db/session.py — Supabase/PostgreSQL async session with direct supabase-py client
"""
from supabase import create_client, Client
from backend.config import settings
from loguru import logger

_supabase_client: Client = None


def get_supabase() -> Client:
    """Get singleton Supabase client."""
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(
            settings.supabase_url,
            settings.supabase_anon_key,
        )
    return _supabase_client


async def save_run(run_id: str, problem_raw: str, domain: str = None, geography: str = None) -> dict:
    """Create a new run record in Supabase."""
    try:
        client = get_supabase()
        result = client.table("runs").insert({
            "id": run_id,
            "problem_raw": problem_raw,
            "domain": domain,
            "geography": geography,
            "status": "running",
            "agent_statuses": {},
        }).execute()
        return result.data[0] if result.data else {}
    except Exception as e:
        logger.error(f"Failed to save run {run_id}: {e}")
        return {}


async def update_run_status(run_id: str, status: str, agent_statuses: dict = None, error: str = None):
    """Update run status and agent statuses."""
    try:
        client = get_supabase()
        update_data = {"status": status}
        if agent_statuses:
            update_data["agent_statuses"] = agent_statuses
        if error:
            update_data["error_message"] = error
        if status in ["completed", "failed"]:
            from datetime import datetime
            update_data["completed_at"] = datetime.utcnow().isoformat()

        client.table("runs").update(update_data).eq("id", run_id).execute()
    except Exception as e:
        logger.error(f"Failed to update run {run_id}: {e}")


async def save_agent_output(run_id: str, agent_name: str, layer: int, output_data: dict, latency_ms: int = None):
    """Save individual agent output."""
    try:
        client = get_supabase()
        client.table("agent_outputs").upsert({
            "run_id": run_id,
            "agent_name": agent_name,
            "agent_layer": layer,
            "output_data": output_data,
            "latency_ms": latency_ms,
        }, on_conflict="run_id,agent_name").execute()
    except Exception as e:
        logger.error(f"Failed to save output for {agent_name}: {e}")


async def get_run(run_id: str) -> dict:
    """Fetch a run record."""
    try:
        client = get_supabase()
        result = client.table("runs").select("*").eq("id", run_id).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Failed to fetch run {run_id}: {e}")
        return None


async def get_agent_outputs(run_id: str) -> list:
    """Fetch all agent outputs for a run."""
    try:
        client = get_supabase()
        result = client.table("agent_outputs").select("*").eq("run_id", run_id).execute()
        return result.data or []
    except Exception as e:
        logger.error(f"Failed to fetch outputs for {run_id}: {e}")
        return []


async def get_user_runs(user_id: str, limit: int = 10) -> list:
    """Fetch a user's past runs."""
    try:
        client = get_supabase()
        result = (
            client.table("runs")
            .select("id, problem_raw, domain, status, created_at, completed_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Failed to fetch runs for user {user_id}: {e}")
        return []


async def get_recent_runs(limit: int = 20) -> list:
    """Fetch recent runs (demo mode; no auth)."""
    try:
        client = get_supabase()
        result = (
            client.table("runs")
            .select("id, problem_raw, domain, geography, status, created_at, completed_at, error_message")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Failed to fetch recent runs: {e}")
        return []


async def delete_run(run_id: str):
    """Delete a run and all associated data."""
    try:
        client = get_supabase()
        client.table("runs").delete().eq("id", run_id).execute()
    except Exception as e:
        logger.error(f"Failed to delete run {run_id}: {e}")


# Map agent_name -> RunContext field name for building context from DB
AGENT_TO_CONTEXT_FIELD = {
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


async def build_context_from_db(run_id: str) -> "RunContext | None":
    """Build a RunContext from database when not in active_runs (e.g. after refresh)."""
    from backend.context import RunContext
    from datetime import datetime

    run = await get_run(run_id)
    if not run:
        return None
    outputs = await get_agent_outputs(run_id)

    ctx = RunContext(
        run_id=run_id,
        problem_raw=run.get("problem_raw", ""),
        domain=run.get("domain"),
        geography=run.get("geography"),
    )
    ctx.status = run.get("agent_statuses") or {}
    try:
        if run.get("created_at"):
            ts = str(run["created_at"]).replace("Z", "+00:00")
            ctx.created_at = datetime.fromisoformat(ts)
    except Exception:
        pass
    try:
        if run.get("completed_at"):
            ts = str(run["completed_at"]).replace("Z", "+00:00")
            ctx.completed_at = datetime.fromisoformat(ts)
    except Exception:
        pass

    for out in outputs:
        agent_name = out.get("agent_name")
        output_data = out.get("output_data") or {}
        field_name = AGENT_TO_CONTEXT_FIELD.get(agent_name)
        if field_name:
            if agent_name == "Agent0_Refiner":
                ctx.problem_refined = output_data.get("problem_refined", ctx.problem_raw)
            else:
                setattr(ctx, field_name, output_data)
        if agent_name:
            ctx.status[agent_name] = "done" if output_data else "error"

    return ctx
