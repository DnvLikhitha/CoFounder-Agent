"""External tools for agents: SerpAPI (search), FRED (economic data)."""
from .search import search_web
from .fred_client import fetch_fred_data

__all__ = ["search_web", "fetch_fred_data"]
