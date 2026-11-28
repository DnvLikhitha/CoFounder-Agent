"""Validate recognized subscription revenue against committed founder pricing."""
from decimal import Decimal

from pydantic import ConfigDict, Field, ValidationError

from backend.run_worker.live_outputs import Financials, Money, Output, Projection


class Prices(Output):
    model_config = ConfigDict(extra="forbid")
    price_monthly_usd: Money
    price_annual_usd: Money


class Customers(Output):
    model_config = ConfigDict(extra="forbid")
    monthly: int = Field(ge=0)
    annual: int = Field(ge=0)


class ReviewedProjection(Projection):
    tier_customers: dict[str, Customers]
    revenue_usd: Money


class ReviewedForecast(Financials):
    pricing_assumptions: dict[str, Prices]
    monthly_projections: list[ReviewedProjection] = Field(min_length=12, max_length=12)
    total_12mo_revenue_usd: Money
    arr_month_12_usd: Money


def approved_prices(pricing):
    return {tier["tier_name"]: {"price_monthly_usd": tier["price_monthly_usd"],
                               "price_annual_usd": tier["price_annual_usd"]} for tier in pricing["tiers"]}


def reviewed_forecast_error(content, pricing):
    try:
        forecast = ReviewedForecast.model_validate(content)
    except ValidationError:
        return "The revised forecast must disclose its prices, customer allocations, and revenue calculations."
    approved = approved_prices(pricing)
    if {name: prices.model_dump() for name, prices in forecast.pricing_assumptions.items()} != approved:
        return "The revised forecast must use the founder-approved prices for every tier."

    annualized = {name: (Decimal(str(tier["price_monthly_usd"])) * 12, Decimal(str(tier["price_annual_usd"])))
                  for name, tier in approved.items()}
    annual_run_rate = Decimal(0)
    recognized_revenue = Decimal(0)
    for month in forecast.monthly_projections:
        if month.tier_customers.keys() - annualized.keys() or sum(
                count.monthly + count.annual for count in month.tier_customers.values()) != month.total_customers:
            return "Monthly customer allocations must use approved tiers and match total customers."
        annual_run_rate = sum((annualized[tier][0] * count.monthly + annualized[tier][1] * count.annual
                               for tier, count in month.tier_customers.items()), Decimal(0))
        for amount in (month.mrr_usd, month.revenue_usd):
            if abs(Decimal(str(amount)) * 12 - annual_run_rate) > Decimal("0.06"):
                return "Monthly recurring revenue must match the approved prices and customer allocations."
        recognized_revenue += Decimal(str(month.revenue_usd))
    if abs(Decimal(str(forecast.arr_month_12_usd)) - annual_run_rate) > Decimal("0.005"):
        return "Year-end ARR must match the annualized revenue from the final month's customer allocations."
    if abs(Decimal(str(forecast.total_12mo_revenue_usd)) - recognized_revenue) > Decimal("0.005"):
        return "Total 12-month revenue must match the sum of monthly recognized revenue."
    return None
