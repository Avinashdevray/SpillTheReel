"""
app/main.py — FastAPI application entry point for SpillTheReel.

Responsibilities:
- Create and configure the FastAPI app.
- Register CORS middleware.
- Mount API routes.
- Expose /health check.
- Configure Cognee (LLM, embeddings, graph DB) at startup.
"""

import os
import sys
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load .env FIRST — must happen before any os.getenv() calls
load_dotenv()

# Pin Cognee's storage directory to backend/.cognee_data/ so the knowledge
# graph survives pip upgrades and venv recreation.
# This must be set BEFORE cognee is imported anywhere in the process.
os.environ["COGNEE_DATA_PATH"] = os.path.join(os.getcwd(), ".cognee_data")

# Prevent Cognee from enforcing multi-user access control (causes conflicts)
os.environ.setdefault("ENABLE_BACKEND_ACCESS_CONTROL", "false")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router

# Configure standard logging to stderr
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("spillthereel.main")


def _configure_cognee() -> None:
    """
    Configure Cognee LLM, embedding, and graph DB settings at startup.
    Raises RuntimeError if required environment variables are missing.
    """
    import cognee

    groq_api_key = os.getenv("GROQ_API_KEY")
    neo4j_uri = os.getenv("NEO4J_URI")
    neo4j_user = os.getenv("NEO4J_USERNAME")
    neo4j_pass = os.getenv("NEO4J_PASSWORD")

    missing = [
        name
        for name, val in [
            ("GROQ_API_KEY", groq_api_key),
            ("NEO4J_URI", neo4j_uri),
            ("NEO4J_USERNAME", neo4j_user),
            ("NEO4J_PASSWORD", neo4j_pass),
        ]
        if not val
    ]
    if missing:
        raise RuntimeError(
            f"[ConfigurationError] Missing required environment variables: {missing}. "
            "Check your backend/.env file."
        )

    # LLM — Groq via OpenAI-compatible endpoint
    cognee.config.set_llm_provider("openai")
    cognee.config.set_llm_endpoint("https://api.groq.com/openai/v1")
    cognee.config.set_llm_api_key(groq_api_key)
    cognee.config.set_llm_model("openai/llama-3.3-70b-versatile")

    # Embeddings — local fastembed (no external API calls required)
    cognee.config.set_embedding_provider("fastembed")
    cognee.config.set_embedding_model("BAAI/bge-small-en-v1.5")
    cognee.config.set_embedding_dimensions(384)

    # Graph DB — Neo4j AuraDB
    cognee.config.set_graph_database_provider("neo4j")
    cognee.config.set_graph_db_config({
        "graph_database_url": neo4j_uri,
        "graph_database_username": neo4j_user,
        "graph_database_password": neo4j_pass,
    })

    # Vector DB — local LanceDB
    cognee.config.set_vector_db_provider("lancedb")

    logger.info("Cognee configuration applied successfully.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler — runs startup logic before serving requests."""
    logger.info("SpillTheReel backend starting up...")
    try:
        _configure_cognee()
    except Exception as exc:
        logger.critical(f"Startup failed during Cognee configuration: {exc}", exc_info=True)
        raise

    yield

    logger.info("SpillTheReel backend shutting down.")


# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="SpillTheReel API",
    description="AI-powered audio-visual second brain — ingests reels, stores in a knowledge graph.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — permissive for local/Expo dev; tighten in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount all API routes under /
app.include_router(router)


@app.get("/health", tags=["Meta"])
async def health_check():
    """Liveness probe — returns 200 OK when the service is running."""
    return {"status": "ok", "service": "SpillTheReel Backend", "version": "0.1.0"}
