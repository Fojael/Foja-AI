from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.memory import router as memory_router
from app.core.config import settings
from app.core.database import close_db, init_db
from app.services.ai.ollama import get_ollama_status
from app.services.memory.extraction import (
    shutdown_extraction_tasks,
    startup_extraction_tasks,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    - On startup: initializes extraction task manager state and database tables.
    - Guaranteed cleanup: database engine disposal and task draining are always
      attempted even if startup fails or extraction shutdown raises.
    - Shutdown order:
        1. Stop accepting new extraction tasks.
        2. Wait for active extraction tasks (up to timeout).
        3. Cancel and await remaining tasks if timed out.
        4. Dispose database engine.
    - Original startup and shutdown exceptions are never silently swallowed.
    """
    try:
        startup_extraction_tasks()
        await init_db()
        yield
    finally:
        # Guaranteed cleanup: ensure database engine is closed even if extraction draining raises
        try:
            await shutdown_extraction_tasks()
        finally:
            await close_db()


app = FastAPI(
    title=settings.APP_NAME,
    description=settings.DESCRIPTION,
    version=settings.APP_VERSION,
    lifespan=lifespan
)

# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(chat_router)
app.include_router(memory_router)


@app.get("/")
async def home():
    """Root metadata endpoint."""
    return {
        "assistant": settings.APP_NAME,
        "message": "Welcome to your personal AI assistant!",
        "version": settings.APP_VERSION,
        "status": "running"
    }


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "assistant": settings.APP_NAME,
        "backend": "FastAPI"
    }


@app.get("/api/ollama/status")
async def ollama_status():
    """Check Ollama service connectivity using the centralized AI service."""
    return await get_ollama_status()
