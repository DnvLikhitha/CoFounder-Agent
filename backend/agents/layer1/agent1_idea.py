"""
Layer 1: Agent 1 — Startup Idea Generator
Generates 3 startup concepts and selects the strongest one.
Uses SerpAPI to validate similar startups exist and find naming conflicts.
"""
from backend.agents.base import BaseAgent
from backend.context import RunContext
from backend.tools.search import search_web


PROMPT_TEMPLATE = """You are a serial entrepreneur and YC partner who has seen 1000+ startup pitches.

Problem Statement: {problem_refined}
Domain: {domain}
Target Geography: {geography}
{external_research_block}

Step 1: Generate EXACTLY 3 distinct startup ideas that solve this problem in fundamentally different ways.
Step 2: Evaluate each on: market size, differentiation, feasibility, and timing.
Step 3: Select the BEST one.

For your selected idea, output EXACTLY this JSON:

```json
{{
  "startup_name": "Two or three memorable words (e.g. 'NestFinder AI')",
  "tagline": "Under 10 words that captures the essence",
  "one_liner": "One sentence explaining what it does and who it's for",
  "value_proposition": "What unique value does this deliver that no one else does?",
  "target_customer": "Specific description (e.g. 'B2B SaaS for HR teams at 50-200 person companies')",
  "key_differentiator": "The core thing that makes this 10x better than existing solutions",
  "unfair_advantage": "What gives this startup an edge competitors can't easily copy?",
  "business_type": "B2B|B2C|B2B2C|Marketplace|Platform",
  "rejected_ideas": [
    {{"name": "Idea 1 name", "reason_rejected": "why not chosen"}},
    {{"name": "Idea 2 name", "reason_rejected": "why not chosen"}}
  ]
}}
```
"""


class Agent1_IdeaGenerator(BaseAgent):
    name = "Agent1_IdeaGenerator"
    layer = 1

    async def fetch_research(self, ctx: RunContext) -> str:
        query = f"startups solving {ctx.problem_refined or ctx.problem_raw[:100]} {ctx.domain or ''}"
        return await search_web(query, num_results=5, caller=self.name)

    def build_prompt(self, ctx: RunContext, external_research: str = "") -> str:
        block = f"\nExternal Research (use to validate ideas, avoid naming conflicts):\n{external_research}\n" if external_research else ""
        return PROMPT_TEMPLATE.format(
            problem_refined=ctx.problem_refined or ctx.problem_raw,
            domain=ctx.domain or "General",
            geography=ctx.geography or "Global",
            external_research_block=block,
        )

    def parse_output(self, raw: str) -> dict:
        return self.extract_json(raw)

    def write_to_context(self, ctx: RunContext, parsed: dict) -> RunContext:
        ctx.startup_idea = parsed
        return ctx

    def write_fallback(self, ctx: RunContext) -> RunContext:
        ctx.startup_idea = {
            "startup_name": "StartupAI",
            "tagline": "AI-powered solution",
            "one_liner": "We solve this problem with AI.",
            "value_proposition": "Fast and easy solution",
            "target_customer": "Early adopters",
            "key_differentiator": "AI-powered",
            "unfair_advantage": "First mover",
            "business_type": "B2B",
        }
        return ctx
