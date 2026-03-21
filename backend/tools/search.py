"""
tools/search.py — SerpAPI web search for agents
"""
import httpx
from loguru import logger

from backend.config import settings


async def search_web(query: str, num_results: int = 5, caller: str = "") -> str:
    """
    Run a web search via SerpAPI and return a summary string for prompt injection.
    Returns empty string if key missing or request fails.
    """
    if not settings.serpapi_api_key:
        logger.info(f"🔍 SerpAPI [{caller or '?'}]: SKIPPED (no SERPAPI_API_KEY)")
        return ""

    logger.info(f"🔍 SerpAPI [{caller or '?'}]: Calling — query='{query[:60]}{'...' if len(query) > 60 else ''}'")
    url = "https://serpapi.com/search"
    params = {
        "q": query,
        "api_key": settings.serpapi_api_key,
        "num": min(num_results, 10),
        "engine": "google",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning(f"🔍 SerpAPI: FAILED — {e}")
        return ""

    # Extract organic results and knowledge graph
    lines = []
    organic = data.get("organic_results", [])[:num_results]
    for i, r in enumerate(organic, 1):
        title = r.get("title", "")
        snippet = r.get("snippet", "")
        link = r.get("link", "")
        if title or snippet:
            lines.append(f"[{i}] {title}\n{snippet}\nSource: {link}")

    kg = data.get("knowledge_graph", {})
    if kg:
        kg_title = kg.get("title", "")
        kg_desc = kg.get("description", "")
        kg_type = kg.get("type", "")
        if kg_title or kg_desc:
            lines.insert(0, f"[Knowledge] {kg_title} ({kg_type})\n{kg_desc}")

    if not lines:
        logger.info("🔍 SerpAPI: OK but no results extracted")
        return ""
    logger.info(f"🔍 SerpAPI [{caller or '?'}]: OK — {len(lines)} items for prompt")
    return "--- Web Search Results ---\n" + "\n\n".join(lines) + "\n--- End Search ---"


