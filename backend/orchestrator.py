"""
orchestrator.py — Core pipeline runner with hybrid sequential-parallel execution
and real-time SSE event broadcasting.
"""
import asyncio
from datetime import datetime
from typing import Callable, Optional
from loguru import logger

from backend.context import RunContext
from backend.agents import (
    Agent0_Refiner, Agent1_IdeaGenerator, Agent2_MarketResearch,
    Agent3_Competitors, Agent4_Personas, Agent5_ProductDesigner,
    Agent6_MVPRoadmap, Agent7_BusinessModel, Agent8_Pricing,
    Agent9_Financials, Agent10_RiskAnalyst, Agent11_TechArchitecture,
    Agent12_DatabaseSchema, Agent13_Security, Agent14_PitchDeck,
    Agent15_ExecutiveSummary,
)
from backend.llm.client import LLMClient


class StartupOrchestrator:
    """
    Hybrid sequential-parallel pipeline orchestrator.

    Phase 1 (Sequential): Agents 0-5 — Foundation layer
    Phase 2 (Parallel):   Agents 6,7,8,9,10 — Business design layer
    Phase 3 (Sequential): Agents 11-13 — Technical design layer
    Phase 4 (Parallel):   Agents 14,15 — Investor output layer
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()

    async def run(
        self,
        problem: str,
        run_id: str,
        domain: Optional[str] = None,
        geography: Optional[str] = None,
        event_callback: Optional[Callable] = None,
    ) -> RunContext:
        """
        Execute the full 16-agent pipeline and return the completed RunContext.

        event_callback: async function(event_type: str, data: dict) -> None
                        Called for each SSE event to push updates to the client.
        """
        ctx = RunContext(
            run_id=run_id,
            problem_raw=problem,
            domain=domain,
            geography=geography,
        )

        # Initialize all agent statuses as pending
        all_agents = [
            "Agent0_Refiner", "Agent1_IdeaGenerator", "Agent2_MarketResearch",
            "Agent3_Competitors", "Agent4_Personas", "Agent5_ProductDesigner",
            "Agent6_MVPRoadmap", "Agent7_BusinessModel", "Agent8_Pricing",
            "Agent9_Financials", "Agent10_RiskAnalyst", "Agent11_TechArchitecture",
            "Agent12_DatabaseSchema", "Agent13_Security", "Agent14_PitchDeck",
            "Agent15_ExecutiveSummary",
        ]
        ctx.status = {agent: "pending" for agent in all_agents}

        if event_callback:
            await event_callback("pipeline_start", {
                "run_id": run_id,
                "total_agents": 16,
                "phases": ["Foundation (0-5)", "Business (6-10, parallel)", "Technical (11-13)", "Investor Output (14-15, parallel)"]
            })

        try:
            # ── Phase 1: Sequential Foundation ──────────────────────────────
            logger.info(f"[{run_id}] Phase 1: Sequential foundation")
            for AgentClass in [
                Agent0_Refiner, Agent1_IdeaGenerator, Agent2_MarketResearch,
                Agent3_Competitors, Agent4_Personas, Agent5_ProductDesigner,
            ]:
                agent = AgentClass(self.llm)
                ctx = await agent.run(ctx, event_callback)

            # ── Phase 2: Parallel Business Layer ────────────────────────────
            logger.info(f"[{run_id}] Phase 2: Parallel business layer")

            async def run_agent_and_merge(AgentClass):
                agent = AgentClass(self.llm)
                result_ctx = await agent.run(ctx, event_callback)
                return result_ctx

            parallel_results = await asyncio.gather(
                run_agent_and_merge(Agent6_MVPRoadmap),
                run_agent_and_merge(Agent7_BusinessModel),
                run_agent_and_merge(Agent8_Pricing),
                run_agent_and_merge(Agent9_Financials),
                run_agent_and_merge(Agent10_RiskAnalyst),
                return_exceptions=True,
            )

            for result in parallel_results:
                if isinstance(result, Exception):
                    logger.error(f"Parallel agent error: {result}")
                    continue
                ctx.merge(result)

            # ── Phase 3: Sequential Technical Layer ─────────────────────────
            logger.info(f"[{run_id}] Phase 3: Sequential technical layer")
            for AgentClass in [Agent11_TechArchitecture, Agent12_DatabaseSchema, Agent13_Security]:
                agent = AgentClass(self.llm)
                ctx = await agent.run(ctx, event_callback)

            # ── Phase 4: Parallel Investor Output ───────────────────────────
            logger.info(f"[{run_id}] Phase 4: Parallel investor output")
            investor_results = await asyncio.gather(
                run_agent_and_merge(Agent14_PitchDeck),
                run_agent_and_merge(Agent15_ExecutiveSummary),
                return_exceptions=True,
            )

            for result in investor_results:
                if isinstance(result, Exception):
                    logger.error(f"Investor agent error: {result}")
                    continue
                ctx.merge(result)

            ctx.completed_at = datetime.utcnow()

            if event_callback:
                await event_callback("pipeline_complete", {
                    "run_id": run_id,
                    "total_time_ms": int((ctx.completed_at - ctx.created_at).total_seconds() * 1000),
                    "completed_agents": sum(1 for s in ctx.status.values() if s == "done"),
                    "failed_agents": sum(1 for s in ctx.status.values() if s.startswith("error")),
                })

            logger.info(f"✅ Pipeline complete for run {run_id}")
            return ctx

        except Exception as e:
            logger.error(f"❌ Pipeline failed for run {run_id}: {e}")
            if event_callback:
                await event_callback("pipeline_error", {
                    "run_id": run_id,
                    "error": str(e),
                })
            ctx.completed_at = datetime.utcnow()
            raise
