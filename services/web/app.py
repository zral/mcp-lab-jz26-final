#!/usr/bin/env python3
"""
Microservice Web Interface

Web interface that calls the Agent service over HTTP.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
import os
from datetime import datetime
from typing import Dict, Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import uvicorn

# Logging
def _setup_logging(log_file: str) -> logging.Logger:
    """
    Log to stdout AND to a file, without a shell pipeline.

    The compose files used to run `sh -c "python app.py | tee /app/logs/x.log"`.
    That made /bin/sh PID 1, and sh does not forward SIGTERM to its children --
    so Python never saw the signal, uvicorn never shut down gracefully, and the
    lifespan shutdown below never ran. Doing the tee in Python instead lets the
    process be PID 1 and receive signals directly.
    """
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        handlers.append(logging.FileHandler(log_file))
    except OSError:
        # No log directory -- running outside Docker. stdout is enough.
        pass

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=handlers,
        force=True,
    )
    return logging.getLogger(__name__)


logger = _setup_logging(os.getenv("LOG_FILE", "/app/logs/web.log"))

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start-up and shutdown. Replaces the deprecated @app.on_event hooks."""
    logger.info("Starting Ingrid's Travel Services web interface...")
    logger.info(f"Agent service URL: {AGENT_SERVICE_URL}")
    yield
    await http_client.aclose()
    logger.info("Web interface stopped")


# FastAPI app
app = FastAPI(
    title="Ingrid's Travel Services",
    description="Web interface for intelligent travel services",
    version="1.0.0",
    lifespan=lifespan,
)

# Templates
templates = Jinja2Templates(directory="templates")

# HTTP client used to reach the agent service
http_client = httpx.AsyncClient()

# Request/response models
class QueryRequest(BaseModel):
    query: str

class QueryResponse(BaseModel):
    success: bool
    response: str
    timestamp: str
    agent_connected: bool

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    agent_connected: bool

# Agent service URL
AGENT_SERVICE_URL = os.getenv("AGENT_SERVICE_URL", "http://travel-agent:8001")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Serve the chat interface."""
    # NOTE: request comes FIRST. The old form,
    # TemplateResponse("index.html", {"request": request}), was deprecated
    # in Starlette 0.29 and removed in 1.0. It now fails with
    # "TypeError: unhashable type: 'dict'", because the context dict lands
    # where the template name should be and is used as a cache key.
    return templates.TemplateResponse(request, "index.html")

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check."""
    # Is the agent service reachable?
    agent_connected = False
    try:
        response = await http_client.get(f"{AGENT_SERVICE_URL}/health", timeout=5.0)
        agent_connected = response.status_code == 200
    except:
        pass
    
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now().isoformat(),
        agent_connected=agent_connected
    )

@app.post("/query", response_model=QueryResponse)
async def process_query(query_request: QueryRequest):
    """Forward a user query to the agent service."""
    try:
        logger.info(f"Forwarding query to the agent service: {query_request.query}")
        
        # Call the agent service
        response = await http_client.post(
            f"{AGENT_SERVICE_URL}/query",
            json={"query": query_request.query},
            timeout=30.0
        )
        response.raise_for_status()
        
        result = response.json()
        
        return QueryResponse(
            success=True,
            response=result.get("response", "No response received"),
            timestamp=datetime.now().isoformat(),
            agent_connected=True
        )
        
    except httpx.TimeoutException:
        logger.error("Timeout ved kall til agent service")
        raise HTTPException(status_code=504, detail="Agent service timeout")
    except httpx.ConnectError:
        logger.error("Cannot reach the agent service")
        raise HTTPException(status_code=503, detail="Agent service unavailable")
    except Exception as e:
        logger.error(f"Processing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/examples")
async def examples():
    """Example queries shown in the interface."""
    return {
        "examples": [
            {
                "title": "🌤️ Weather forecast",
                "description": "Get a detailed forecast for your destination",
                "query": "What is the weather in Oslo this week?"
            },
            {
                "title": "🧳 What to pack",
                "description": "Ask what the week ahead calls for",
                "query": "I am going to Tromso on Friday - what should I pack?"
            },
            {
                "title": "☔ Ask Ingrid about rain",
                "description": "She is from Bergen and has opinions",
                "query": "Do you actually enjoy the rain in Bergen?"
            },
            {
                "title": "🌍 International weather",
                "description": "Get forecasts for destinations abroad",
                "query": "What is the forecast for Copenhagen this week?"
            },
            {
                "title": "⏰ Best time to travel",
                "description": "Advice on when to travel, based on the outlook",
                "query": "When is the best time to visit Lofoten in October?"
            }
        ]
    }

if __name__ == "__main__":
    logger.info("Starting Web Interface on port 8080...")
    uvicorn.run(app, host="0.0.0.0", port=8080)
