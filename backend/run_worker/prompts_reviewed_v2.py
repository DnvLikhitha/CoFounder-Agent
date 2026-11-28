"""Require auditable approved-price calculations in revised forecasts."""
from types import SimpleNamespace

from backend.run_worker.prompts_reviewed_v1 import run_agent as render_reviewed


FORECAST_REQUIREMENTS = """
For this revised forecast, add a top-level pricing_assumptions object keyed by exact tier name.
Include price_monthly_usd and price_annual_usd for every approved tier and copy the approved prices exactly.
For each month, add a tier_customers object keyed by tier name, with nonnegative integer monthly and annual
counts for active customers on each billing plan. You may omit tiers without active customers in a month.
The counts must add up to total_customers. For this forecast, use subscription revenue only.
Calculate both mrr_usd and revenue_usd from monthly customers times monthly price plus annual customers times
annual price divided by 12. Round each monthly amount to cents. Set total_12mo_revenue_usd to the sum of the
12 rounded revenue_usd amounts. Set arr_month_12_usd to the final month's annualized amount before rounding MRR.
"""


async def run_agent(step_id, body, upstream, llm):
    if step_id != "financial_projections" or not upstream.get("pricing_strategy", {}).get("founder_price_revision"):
        return await render_reviewed(step_id, body, upstream, llm)

    async def complete(prompt, **options):
        return await llm.complete(prompt + FORECAST_REQUIREMENTS, **options)

    return await render_reviewed(step_id, body, upstream, SimpleNamespace(complete=complete))
