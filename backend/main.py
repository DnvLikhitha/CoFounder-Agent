"""
main.py — FastAPI application entry point
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from loguru import logger

from backend.config import settings
from backend.api.routes import run as run_router
from backend.api.routes import stream as stream_router
from backend.api.routes import export as export_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 AI Startup Co-Founder Agent API starting...")
    logger.info(f"   Environment: {settings.environment}")
    logger.info(f"   Supabase: {settings.supabase_url}")
    logger.info(f"   Groq key: {'✅ Set' if settings.groq_api_key else '❌ Missing'}")
    yield
    logger.info("🛑 Shutting down...")


app = FastAPI(
    title="AI Startup Co-Founder Agent",
    description="Transform a one-line problem into a complete investor-ready startup plan with 16 specialized AI agents.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list + ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(run_router.router)
app.include_router(stream_router.router)
app.include_router(export_router.router)


@app.get("/")
async def root():
    return {
        "service": "AI Startup Co-Founder Agent",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "environment": settings.environment}
