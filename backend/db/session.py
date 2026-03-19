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
