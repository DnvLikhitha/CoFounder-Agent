"""
Layer 1: Agent 2 — Market Research Analyst
Estimates market size, growth, and dynamics like a McKinsey analyst.
Uses SerpAPI for market data + FRED for macro economic indicators.
"""
from backend.agents.base import BaseAgent, Research, source_urls
from backend.context import AgentInputs
from backend.tools.search import search_web
from backend.tools.fred_client import fetch_fred_data


PROMPT_TEMPLATE = """You are a Senior Market Research Analyst at McKinsey & Company.

Startup: {startup_name}
Problem: {problem_refined}
Domain: {domain}
Target Customer: {target_customer}
{external_research_block}

Conduct a comprehensive market sizing analysis.

Use the TAM-SAM-SOM framework:
- TAM (Total Addressable Market): Everyone who has this problem globally
- SAM (Serviceable Addressable Market): The portion you can realistically reach
- SOM (Serviceable Obtainable Market): What you can capture in years 1-3

Output EXACTLY this JSON:

```json
{{
  "tam_usd_billions": 12.5,
  "sam_usd_billions": 2.1,
  "som_usd_millions": 45,
  "cagr_percent": 18.5,
  "market_maturity": "emerging|growing|mature|declining",
  "market_trends": [
    "Trend 1: description",
    "Trend 2: description",
    "Trend 3: description"
  ],
  "target_segments": [
    {{"segment": "Segment name", "size_percent": 40, "pain_level": "high"}},
    {{"segment": "Segment name", "size_percent": 35, "pain_level": "medium"}}
  ],
  "key_market_drivers": ["driver1", "driver2", "driver3"],
  "regulatory_environment": "Brief description of relevant regulations",
  "market_timing": "Why NOW is the right time to enter this market",
  "data_sources_referenced": []
}}
```

Label market sizes as estimates and describe the basis in market_timing.
List only sources available in the input. Use null for values that cannot be estimated responsibly.
"""


class Agent2_MarketResearch(BaseAgent):
    name = "Agent2_MarketResearch"

    async def fetch_research(self, ctx: AgentInputs) -> Research:
        domain = ctx.domain or "market"
        search_q = f"{domain} market size TAM SAM 2024 2025"
        search_res = await search_web(search_q, num_results=5, caller=self.name)
        fred_res = await fetch_fred_data(caller=self.name)
        parts = [p for p in [search_res, fred_res] if p]
        sources = source_urls(search_res)
        return Research("\n\n".join(parts), {"serpapi_sources": sources, "fred_data": fred_res})

    def build_prompt(self, ctx: AgentInputs, external_research: str = "") -> str:
        idea = ctx.startup_idea
        block = f"\nExternal Research (use to ground your estimates):\n{external_research}\n" if external_research else ""
        return PROMPT_TEMPLATE.format(
            startup_name=idea.get("startup_name", "Our Startup"),
            problem_refined=ctx.problem_refined,
            domain=ctx.domain or "General",
            target_customer=idea.get("target_customer", ""),
            external_research_block=block,
        )

    def parse_output(self, raw: str) -> dict:
        return self.extract_json(raw)
