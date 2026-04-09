#!/usr/bin/env python3
"""
Supervisor Agent API Service
Exposes the supervisor agent as a REST API service for
external frontend integrations.
Built with FastAPI and Uvicorn.

Usage:
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

from contextlib import asynccontextmanager
from datetime import datetime
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from logger import setup_logger
from routes.mcp_routes import router as mcp_router
from routes.supervisor_routes import (
    router as supervisor_router,
    initialize_agent,
    get_supervisor_agent,
)

logger = setup_logger(__name__)


# ==================== Lifespan ====================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    initialize_agent()
    logger.info("Supervisor API service started")
    yield
    logger.info("Supervisor API service shutting down")


# ==================== Pydantic Models ====================


class HealthCheckResponse(BaseModel):
    """Health check response"""

    status: str = Field(..., description="Service status")
    message: str = Field(..., description="Status message")
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ==================== FastAPI Setup ====================

app = FastAPI(
    title="Supervisor Agent API",
    description="REST API for the Supervisor Agent",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# Add CORS middleware to allow requests from other frontend projects
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(mcp_router)
app.include_router(supervisor_router)


# ==================== API Endpoints ====================


@app.get("/api/health", response_model=HealthCheckResponse, tags=["Health"])
async def health_check():
    """Health check endpoint to verify API is running"""
    agent = get_supervisor_agent()
    return HealthCheckResponse(
        status="healthy" if agent else "initializing",
        message="Supervisor API is running" if agent else "Agent is initializing",
    )


# ==================== Error Handlers ====================


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom handler for HTTP exceptions"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "message": exc.detail,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Custom handler for general exceptions"""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "message": "Internal server error",
            "timestamp": datetime.utcnow().isoformat(),
        },
    )


# ==================== Root Endpoint ====================


@app.get("/", tags=["Root"])
async def root():
    """
    Root endpoint with API information and links to documentation
    """
    return {
        "name": "Supervisor Agent API",
        "version": "1.0.0",
        "documentation": "/api/docs",
        "redoc": "/api/redoc",
        "endpoints": {
            "health": "/api/health",
            "supervisor_chat": "/api/supervisor/chat",
            "supervisor_agent": "/api/supervisor/agent",
        },
    }


# ==================== Entry Point ====================

if __name__ == "__main__":
    import uvicorn

    # Run the API server
    uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="info", reload=True)
