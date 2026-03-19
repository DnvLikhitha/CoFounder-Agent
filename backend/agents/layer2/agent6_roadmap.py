"""
Layer 2: Agent 6 — MVP Roadmap Planner (parallel-eligible)
Breaks MVP into 3 sprints with tasks, owners, and dependencies.
"""
from backend.agents.base import BaseAgent
from backend.context import RunContext


PROMPT_TEMPLATE = """You are an Agile Product Manager at a lean startup. Budget is $0. Team is 1-2 developers.

Startup: {startup_name}
Must-Have Features: {must_have_features}
Tech Business Type: {business_type}

Design a 3-sprint MVP roadmap (each sprint = 2 weeks).
Be specific and actionable — no fluff.

Output EXACTLY this JSON:

```json
{{
  "sprints": [
    {{
      "sprint_number": 1,
      "sprint_goal": "The ONE thing this sprint proves",
      "duration_weeks": 2,
      "theme": "Foundation",
      "user_stories": [
        {{
          "id": "US-1-1",
          "title": "Story title",
          "as_a": "user type",
          "i_want": "action",
          "so_that": "benefit",
          "story_points": 3,
          "priority": "P0"
        }}
      ],
      "technical_tasks": ["Task 1", "Task 2", "Task 3"],
      "deliverable": "What can be demonstrated at the end of this sprint"
    }},
    {{
      "sprint_number": 2,
      "sprint_goal": "...",
      "duration_weeks": 2,
      "theme": "Core Product",
      "user_stories": [],
      "technical_tasks": [],
      "deliverable": "..."
    }},
    {{
      "sprint_number": 3,
      "sprint_goal": "...",
      "duration_weeks": 2,
      "theme": "Launch Ready",
      "user_stories": [],
      "technical_tasks": [],
      "deliverable": "..."
    }}
  ],
  "total_weeks": 6,
  "mvp_success_criteria": ["Criterion 1", "Criterion 2", "Criterion 3"],
  "first_user_milestone": "When to expect your first 10 paying users"
}}
```
"""


class Agent6_MVPRoadmap(BaseAgent):
    name = "Agent6_MVPRoadmap"
    layer = 2

    def build_prompt(self, ctx: RunContext) -> str:
        idea = ctx.startup_idea
        product = ctx.product_design
        must_haves = [f.get("feature", "") for f in product.get("must_have_features", [])[:5]]
        return PROMPT_TEMPLATE.format(
            startup_name=idea.get("startup_name", "Our Startup"),
            must_have_features=", ".join(must_haves) if must_haves else "Core product features",
            business_type=idea.get("business_type", "B2B SaaS"),
        )

    def parse_output(self, raw: str) -> dict:
        return self.extract_json(raw)

    def write_to_context(self, ctx: RunContext, parsed: dict) -> RunContext:
        ctx.mvp_roadmap = parsed
        return ctx

    def write_fallback(self, ctx: RunContext) -> RunContext:
        ctx.mvp_roadmap = {"sprints": [], "total_weeks": 6}
        return ctx
