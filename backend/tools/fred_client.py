"""
tools/fred_client.py — FRED (Federal Reserve Economic Data) API for macroeconomic data
"""
import httpx
from loguru import logger

from backend.config import settings

# Useful FRED series for startup financial models
FRED_SERIES = {
    "FEDFUNDS": "Federal Funds Rate (%)",
    "CPIAUCSL": "Consumer Price Index (inflation proxy)",
    "UNRATE": "Unemployment Rate (%)",
    "GDP": "Gross Domestic Product",
    "DFF": "Effective Federal Funds Rate",
}


async def fetch_fred_data(series_ids: list[str] | None = None, caller: str = "") -> str:
    """
    Fetch latest observations from FRED for key economic indicators.
    Returns a summary string for prompt injection.
    """
    if not settings.fred_api_key:
        logger.info(f"📊 FRED [{caller or '?'}]: SKIPPED (no FRED_API_KEY)")
        return ""

    ids = series_ids or ["FEDFUNDS", "DFF", "UNRATE"]
    logger.info(f"📊 FRED [{caller or '?'}]: Calling — series={ids}")
    url = "https://api.stlouisfed.org/fred/series/observations"

    lines = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for sid in ids[:5]:  # Limit to 5 series to save quota
                params = {
                    "series_id": sid,
                    "api_key": settings.fred_api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 3,
                }
                try:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                    obs = data.get("observations", [])
                    if obs:
                        latest = obs[0]
                        val = latest.get("value", "N/A")
                        date = latest.get("date", "")
                        label = FRED_SERIES.get(sid, sid)
                        lines.append(f"- {label}: {val} (as of {date})")
                except Exception as e:
                    logger.debug(f"FRED series {sid} failed: {e}")
    except Exception as e:
        logger.warning(f"📊 FRED: FAILED — {e}")
        return ""

    if not lines:
        logger.info("📊 FRED: OK but no data extracted")
        return ""
    logger.info(f"📊 FRED [{caller or '?'}]: OK — {len(lines)} indicators")
    return "--- FRED Economic Data ---\n" + "\n".join(lines) + "\n--- End FRED ---"
