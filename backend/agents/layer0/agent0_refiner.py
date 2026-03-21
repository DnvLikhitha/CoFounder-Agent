"""
Layer 0: Agent 0 — Problem Refiner
Clarifies and enriches raw user input before passing to all other agents.
"""
from backend.agents.base import BaseAgent
from backend.context import RunContext


PROMPT_TEMPLATE = """You are an expert startup advisor and problem analyst.

A user has submitted this raw problem statement:
<user_problem>{problem_raw}</user_problem>

Domain hint: {domain}
Geography: {geography}

Your task is to REFINE and ENRICH this problem statement so it is:
1. Specific (not vague)
2. Focused on a real user pain point
3. Framed as an opportunity

Think step by step about:
- WHO specifically suffers from this problem?
- WHEN and WHERE does this problem occur?
- WHY existing solutions fail?
- What is the scale of this problem?

Then output EXACTLY this JSON:

```json
{{
  "problem_refined": "A 2-3 sentence crisp problem statement",
  "target_user": "Specific description of the primary user who has this problem",
  "pain_intensity": "high|medium|low",
  "existing_solutions": ["solution1", "solution2", "solution3"],
  "why_existing_solutions_fail": "Brief explanation",
  "problem_tags": ["tag1", "tag2", "tag3"],
  "domain_confirmed": "The confirmed domain/industry",
  "opportunity_statement": "One sentence framing this as a market opportunity"
}}
```
"""


class Agent0_Refiner(BaseAgent):
    name = "Agent0_Refiner"
    layer = 0

    def build_prompt(self, ctx: RunContext, external_research: str = "") -> str:
        return PROMPT_TEMPLATE.format(
            problem_raw=self.safe_text(ctx.problem_raw),
            domain=ctx.domain or "Not specified",
            geography=ctx.geography or "Global",
        )

    def parse_output(self, raw: str) -> dict:
        data = self.extract_json(raw)
        return data

    def write_to_context(self, ctx: RunContext, parsed: dict) -> RunContext:
        ctx.problem_refined = parsed.get("problem_refined", ctx.problem_raw)
        # Store enriched metadata in startup_idea placeholder temporarily
        ctx.status["domain_confirmed"] = parsed.get("domain_confirmed", ctx.domain or "General")
        return ctx

    def write_fallback(self, ctx: RunContext) -> RunContext:
        ctx.problem_refined = ctx.problem_raw
        return ctx
