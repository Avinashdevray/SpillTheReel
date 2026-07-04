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

# Prevent Cognee from enforcing multi-user access control (causes conflicts)
os.environ.setdefault("ENABLE_BACKEND_ACCESS_CONTROL", "false")

# Bypass Cognee's LLM connection test — it tests OpenAI's endpoint, not our Groq one.
os.environ.setdefault("COGNEE_SKIP_CONNECTION_TEST", "true")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router

import firebase_admin

# Configure standard logging to stderr
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("spillthereel.main")


def _setup_neo4j_constraints() -> None:
    """Run Neo4j database constraint/index setup queries once at startup."""
    from app.services.repository import get_neo4j_driver
    try:
        driver = get_neo4j_driver()
        db_name = os.environ.get("NEO4J_DATABASE", "neo4j")
        constraints = [
            "CREATE CONSTRAINT user_uid_unique IF NOT EXISTS FOR (u:User) REQUIRE u.firebase_uid IS UNIQUE;",
            "CREATE CONSTRAINT reel_owner_url_unique IF NOT EXISTS FOR (r:Reel) REQUIRE (r.owner_uid, r.url) IS UNIQUE;",
            "CREATE INDEX reel_owner_idx IF NOT EXISTS FOR (r:Reel) ON (r.owner_uid);"
        ]
        logger.info("Setting up Neo4j constraints & indices...")
        with driver.session(database=db_name) as s:
            for constraint in constraints:
                try:
                    s.run(constraint)
                except Exception as c_exc:
                    logger.warning(f"Non-fatal index/constraint setup issue: {c_exc}")
        logger.info("Neo4j constraints and indices configured.")
    except Exception as exc:
        logger.error(f"Failed to setup Neo4j constraints: {exc}")



def _configure_cognee() -> None:
    """
    Configure Cognee LLM, embedding, and graph DB settings at startup.
    Raises RuntimeError if required environment variables are missing.
    """
    import cognee

    groq_api_key = os.getenv("GROQ_API_KEY")
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    bluesmind_key = os.getenv("BLUESMIND")
    neo4j_uri = os.getenv("NEO4J_URI")
    neo4j_user = os.getenv("NEO4J_USERNAME")
    neo4j_pass = os.getenv("NEO4J_PASSWORD")

    missing = [
        name
        for name, val in [
            ("GROQ_API_KEY", groq_api_key),
            ("GEMINI_API_KEY", gemini_api_key),
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

    # LLM — prefer Bluesmind (supports function calling for entity extraction),
    # fall back to Groq (transcription/summary only, no entity graph).
    if bluesmind_key:
        os.environ["OPENAI_API_KEY"] = bluesmind_key
        os.environ["OPENAI_API_BASE"] = "https://api.bluesminds.com/v1/"
        cognee.config.set_llm_provider("openai")
        cognee.config.set_llm_endpoint("https://api.bluesminds.com/v1/")
        cognee.config.set_llm_api_key(bluesmind_key)
        cognee.config.set_llm_model("openai/gpt-4o")
        logger.info("[Config] Cognee LLM → Bluesmind (gpt-4o) — entity extraction enabled")
    else:
        cognee.config.set_llm_provider("openai")
        cognee.config.set_llm_endpoint("https://api.groq.com/openai/v1")
        cognee.config.set_llm_api_key(groq_api_key)
        cognee.config.set_llm_model("openai/llama-3.3-70b-versatile")
        logger.info("[Config] Cognee LLM → Groq (llama-3.3-70b-versatile) — entity extraction skipped")

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
        "graph_database_name": neo4j_user,  # AuraDB uses username as db name
    })

    # Vector DB — local LanceDB
    cognee.config.set_vector_db_provider("lancedb")

    # Redirect Cognee's system directory out of the venv site-packages into the
    # project directory so that the knowledge graph survives pip upgrades and
    # venv recreation.  This cascades to the relational, graph, and vector DB
    # configs automatically.
    cognee.config.system_root_directory(os.path.join(os.getcwd(), ".cognee_data"))

    logger.info("Cognee configuration applied successfully.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler — runs startup logic before serving requests."""
    logger.info("SpillTheReel backend starting up...")
    try:
        from firebase_admin import credentials
        cred = credentials.Certificate('dummy-service-account.json')
        firebase_admin.initialize_app(cred, options={'projectId': 'spillthereel-caa31'})
        logger.info("Firebase Admin SDK initialized successfully.")
    except ValueError:
        logger.warning("Firebase Admin SDK was already initialized.")
    except Exception as exc:
        logger.critical(f"Failed to initialize Firebase Admin: {exc}", exc_info=True)
        raise

    try:
        _configure_cognee()
    except Exception as exc:
        logger.critical(f"Startup failed during Cognee configuration: {exc}", exc_info=True)
        raise

    # Run constraint creation
    _setup_neo4j_constraints()

    yield

    # Teardown: close Neo4j connection
    from app.services.repository import close_neo4j_driver
    close_neo4j_driver()
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
