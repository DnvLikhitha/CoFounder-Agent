"""Format planning estimates without substituting figures for unavailable inputs."""


def format_metric(value, template):
    return template.format(value) if type(value) in {int, float} else "Unavailable"


def investor_metrics(market, financials):
    breakeven = financials.get("breakeven_month")
    return {
        "tam": format_metric(market.get("tam_usd_billions"), "${:g}B"),
        "sam": format_metric(market.get("sam_usd_billions"), "${:g}B"),
        "som": format_metric(market.get("som_usd_millions"), "${:g}M"),
        "cagr": format_metric(market.get("cagr_percent"), "{:g}%"),
        "arr": format_metric(financials.get("arr_month_12_usd"), "${:,.0f}"),
        "breakeven": "Beyond forecast period" if breakeven == 0 else format_metric(breakeven, "Month {}"),
        "ltv": format_metric(financials.get("ltv_usd"), "${:,.0f}"),
        "cac": format_metric(financials.get("cac_usd"), "${:,.0f}"),
        "ltv_cac": format_metric(financials.get("ltv_cac_ratio"), "{:g}x"),
    }
