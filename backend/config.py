"""
config.py — Application settings using Pydantic BaseSettings
"""
from pathlib import Path

from pydantic_settings import BaseSettings
from pydantic import Field

# Load .env from backend/ directory (works whether run from project root or backend/)
_BACKEND_DIR = Path(__file__).resolve().parent
_ENV_FILE = _BACKEND_DIR / ".env"
# Fallback to project root .env if backend/.env doesn't exist
_ENV_PATH = str(_ENV_FILE) if _ENV_FILE.exists() else str(_BACKEND_DIR.parent / ".env")


class Settings(BaseSettings):
    # LLM
    groq_api_key: str = Field(default="", env="GROQ_API_KEY")

    # External tools
    serpapi_api_key: str = Field(default="", env="SERPAPI_API_KEY")
    fred_api_key: str = Field(default="", env="FRED_API_KEY")
    google_ai_api_key: str = Field(default="", env="GOOGLE_AI_API_KEY")
    cerebras_api_key: str = Field(default="", env="CEREBRAS_API_KEY")

    # Supabase
    supabase_url: str = Field(default="", env="SUPABASE_URL")
    supabase_anon_key: str = Field(default="", env="SUPABASE_ANON_KEY")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379", env="REDIS_URL")

    # JWT Auth
    jwt_secret: str = Field(default="changeme", env="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", env="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=1440, env="JWT_EXPIRE_MINUTES")

    # App
    environment: str = Field(default="development", env="ENVIRONMENT")
    max_concurrent_runs: int = Field(default=5, env="MAX_CONCURRENT_RUNS")
    cors_origins: str = Field(default="http://localhost:3000", env="CORS_ORIGINS")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    class Config:
        env_file = _ENV_PATH
        env_file_encoding = "utf-8"


settings = Settings()
