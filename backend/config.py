"""
config.py — Application settings using Pydantic BaseSettings
"""
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

# Load .env from backend/ directory (works whether run from project root or backend/)
_BACKEND_DIR = Path(__file__).resolve().parent
_ENV_FILE = _BACKEND_DIR / ".env"
# Fallback to project root .env if backend/.env doesn't exist
_ENV_PATH = str(_ENV_FILE) if _ENV_FILE.exists() else str(_BACKEND_DIR.parent / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_PATH, env_file_encoding="utf-8",
                                      extra="ignore", hide_input_in_errors=True)
    # LLM
    groq_api_key: str = Field(default="", env="GROQ_API_KEY")

    # External tools
    serpapi_api_key: str = Field(default="", env="SERPAPI_API_KEY")
    fred_api_key: str = Field(default="", env="FRED_API_KEY")

    # Supabase Auth
    supabase_url: str = ""

    # App
    environment: str = Field(default="development", env="ENVIRONMENT")
    max_concurrent_runs: int = Field(default=5, ge=1, env="MAX_CONCURRENT_RUNS")
    database_url: str = ""
    v1_provider_mode: Literal["", "fake", "live"] = ""
    v1_step_concurrency: int = Field(default=2, ge=1, le=8)
    v1_provider_timeout_seconds: float = Field(default=120, gt=0, allow_inf_nan=False)
    v1_run_token_limit: int = Field(default=500_000, gt=0, le=1_000_000_000)
    v1_run_cost_limit_nanousd: int = Field(default=250_000_000, gt=0, le=1_000_000_000_000)
    v1_require_founder_review: bool = False
    v1_require_pricing_review: bool = False
    v1_llm_evaluation: bool = False
    v1_jwt_secret: str = ""
    v1_jwt_issuer: str = "cofounder-agent"
    v1_jwt_audience: str = "cofounder-api"
    cors_origins: str = Field(default="http://localhost:5173", env="CORS_ORIGINS")

    @property
    def production(self) -> bool:
        return self.environment.strip().lower() not in {"development", "local", "test"}

    @property
    def uses_supabase(self) -> bool:
        return self.production or bool(self.supabase_url)

    @property
    def supabase_issuer(self) -> str:
        url = self.supabase_url.rstrip("/")
        if not self.is_origin(url, https_only=self.production) or (
                url.startswith("http://") and urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}):
            raise ValueError("SUPABASE_URL must be an HTTPS origin or a loopback HTTP origin in development")
        return url + "/auth/v1"

    @staticmethod
    def is_origin(value: str, *, https_only: bool) -> bool:
        try:
            url = urlsplit(value)
            return (
                url.scheme in ({"https"} if https_only else {"http", "https"})
                and url.hostname is not None and url.username is None and url.password is None
                and url.port != 0 and not url.path and not url.query and not url.fragment
                and not any(char in value for char in "*?#\\")
                and not any(char.isspace() for char in value)
            )
        except ValueError:
            return False

    def require_v1_provider_mode(self):
        if not self.v1_provider_mode:
            raise ValueError("Set V1_PROVIDER_MODE to live or fake")
        if self.v1_provider_mode == "fake" and self.production:
            raise ValueError("V1_PROVIDER_MODE must be live in production")
        if self.v1_provider_mode == "live" and not self.groq_api_key.strip():
            raise ValueError("GROQ_API_KEY is required for V1_PROVIDER_MODE=live")
        return self.v1_provider_mode

    @property
    def cors_origins_list(self) -> list[str]:
        origins = list(dict.fromkeys(o.strip() for o in self.cors_origins.split(",") if o.strip()))
        if any(not self.is_origin(origin, https_only=self.production) for origin in origins):
            raise ValueError("CORS_ORIGINS must contain exact origins (HTTPS outside development)")
        return origins

    def validate_api_configuration(self):
        self.require_v1_provider_mode()
        self.cors_origins_list
        if self.uses_supabase:
            _ = self.supabase_issuer
        elif len(self.v1_jwt_secret) < 32:
            raise ValueError("V1_JWT_SECRET must be at least 32 characters for local authentication")
        if not self.database_url:
            raise ValueError("DATABASE_URL is required")

settings = Settings()
