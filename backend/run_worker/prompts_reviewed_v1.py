"""Carry founder-approved pricing into the existing financial and investor prompts."""
import json
from types import SimpleNamespace

from backend.run_worker.prompts_v1 import run_agent as render_startup


async def run_agent(step_id, body, upstream, llm):
    if step_id == "pricing_strategy":
        output = await render_startup(step_id, body, upstream, llm)
        output.pop("founder_price_revision", None)
        return output

    pricing = upstream.get("pricing_strategy", {})
    if step_id not in {"financial_projections", "pitch_deck", "executive_summary"} or not pricing.get("founder_price_revision"):
        return await render_startup(step_id, body, upstream, llm)

    prices = [{field: tier[field] for field in ("tier_name", "price_monthly_usd", "price_annual_usd")}
              for tier in pricing["tiers"]]

    async def complete(prompt, **options):
        return await llm.complete(
            prompt + "\nFounder-approved pricing, in USD per tier. Use these monthly and annual prices as assumptions.\n"
            + json.dumps(prices, ensure_ascii=False), **options)

    return await render_startup(step_id, body, upstream, SimpleNamespace(complete=complete))
