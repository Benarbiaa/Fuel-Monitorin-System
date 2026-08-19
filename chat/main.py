"""
main.py
-------
AI Features microservice entry point.

Runs independently on port 8001.
Does NOT import anything from the main pfa/backend/ project.

Endpoints exposed:
  POST /chat    — Conversational Q&A agent
  GET  /alerts  — Alerts enriched with LLM explanations
  GET  /health  — Health check (for debugging + integration testing)
"""

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routes import chat, alerts

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Validate config at startup (fails fast if GEMINI_API_KEY is missing)
# ---------------------------------------------------------------------------
try:
    settings.validate()
except ValueError as exc:
    logger.critical("Configuration error: %s", exc)
    sys.exit(1)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title=" AI Features Microservice",
    description=(
        "Conversational Q&A agent and LLM-enriched alerts for the AGIL fuel "
        "station monitoring system. Runs standalone on port 8001."
    ),
    version="1.0.0",
)

# Allow the Angular dev server (port 4200) and the main backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://localhost:8000", "*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(chat.router)
app.include_router(alerts.router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["Health"])
def health() -> dict:
    return {
        "status": "ok",
        "service": "ai_features",
        "backend_mode": settings.BACKEND_MODE,
        "groq_model": settings.GROQ_MODEL,
    }


# ---------------------------------------------------------------------------
# Run directly: python main.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    logger.info(
        "Starting AI Features microservice on port %d (mode=%s)",
        settings.SERVICE_PORT,
        settings.BACKEND_MODE,
    )
    uvicorn.run("main:app", host="127.0.0.1", port=settings.SERVICE_PORT, reload=True)