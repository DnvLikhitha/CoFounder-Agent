"""FastAPI entry point for the authenticated v1 API."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import psycopg

from backend.config import settings
from backend.run_worker.api import app as v1_app
from backend.run_worker.auth import supabase_keys
from backend.run_worker.store import Store, StoreError
from backend.safe_logging import SafeRequests, configure_safe_logging


@asynccontextmanager
async def lifespan(app):
    configure_safe_logging()
    if settings.production:
        settings.validate_api_configuration()
    yield


async def root():
    return {"service": "AI Startup Co-Founder Agent", "version": "1.0.0", "docs": "/api/v1/docs"}


async def health():
    return {"status": "healthy"}


def ready():
    try:
        settings.validate_api_configuration()
        if not Store(settings.database_url).ready(settings.v1_provider_mode):
            raise StoreError(503, "service_unavailable", "Worker unavailable")
        if settings.production:
            supabase_keys(settings.supabase_issuer).get()
    except (ValueError, psycopg.Error, StoreError):
        return JSONResponse({"status": "unready"}, status_code=503)
    return {"status": "ready"}


def create_app():
    app = FastAPI(title="AI Startup Co-Founder Agent", version="1.0.0", lifespan=lifespan)
    app.mount("/api/v1", v1_app)
    app.add_api_route("/", root, include_in_schema=False)
    app.add_api_route("/health", health)
    app.add_api_route("/ready", ready)
    app.add_middleware(SafeRequests)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID"],
        expose_headers=["Content-Disposition", "WWW-Authenticate"],
    )
    return app


app = create_app()
