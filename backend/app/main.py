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

# Cognee v1.2+ environment configuration (must be set BEFORE imports)
os.environ.setdefault("ENABLE_BACKEND_ACCESS_CONTROL", "false")
os.environ.setdefault("CACHING", "false")
os.environ.setdefault("COGNEE_SKIP_CONNECTION_TEST", "true")
os.environ.setdefault("SYSTEM_ROOT_DIRECTORY", os.path.join(os.getcwd(), ".cognee_data"))

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
            "CREATE INDEX reel_owner_idx IF NOT EXISTS FOR (r:Reel) ON (r.owner_uid);",
            "CREATE FULLTEXT INDEX reel_text IF NOT EXISTS FOR (r:Reel) ON EACH [r.summary, r.transcript];"
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



def _configure_cognee_llm() -> None:
    """Configure only the LLM portion of Cognee (extracted so brain.py can restore it)."""
    import cognee

    from app.services.groq_utils import get_keys

    groq_api_key, groq_api_key2 = get_keys()
    bluesmind_key = os.getenv("BLUESMIND")

    if bluesmind_key:
        os.environ["OPENAI_API_KEY"] = bluesmind_key
        os.environ["OPENAI_API_BASE"] = "https://api.bluesminds.com/v1/"
        cognee.config.set_llm_provider("openai")
        cognee.config.set_llm_endpoint("https://api.bluesminds.com/v1/")
        cognee.config.set_llm_api_key(bluesmind_key)
        cognee.config.set_llm_model("openai/glm-4.6")
        logger.info("[Config] Cognee LLM → Bluesmind (glm-4.6) — entity extraction enabled")
    else:
        api_key = groq_api_key or groq_api_key2
        cognee.config.set_llm_provider("openai")
        cognee.config.set_llm_endpoint("https://api.groq.com/openai/v1")
        cognee.config.set_llm_api_key(api_key)
        cognee.config.set_llm_model("openai/llama-3.3-70b-versatile")
        logger.info("[Config] Cognee LLM → Groq (llama-3.3-70b-versatile) — entity extraction skipped")


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

    # LLM config (extracted for restore-from-backup)
    _configure_cognee_llm()

    # Embeddings — local fastembed (no external API calls required)
    cognee.config.set_embedding_provider("fastembed")
    cognee.config.set_embedding_model("BAAI/bge-small-en-v1.5")
    cognee.config.set_embedding_dimensions(384)

    # Graph DB — Neo4j AuraDB
    neo4j_db_name = os.getenv("NEO4J_DATABASE", neo4j_user)
    cognee.config.set_graph_database_provider("neo4j")
    cognee.config.set_graph_db_config({
        "graph_database_url": neo4j_uri,
        "graph_database_username": neo4j_user,
        "graph_database_password": neo4j_pass,
        "graph_database_name": neo4j_db_name,
    })

    # Vector DB — local LanceDB
    cognee.config.set_vector_db_provider("lancedb")

    logger.info("Cognee configuration applied successfully.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler — runs startup logic before serving requests."""
    logger.info("SpillTheReel backend starting up...")
    try:
        sa_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
        if sa_path:
            cred = firebase_admin.credentials.Certificate(os.path.expanduser(sa_path))
            firebase_admin.initialize_app(cred, options={'projectId': 'spillthereel-caa31'})
        else:
            firebase_admin.initialize_app(options={'projectId': 'spillthereel-caa31'})
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

    # Cognee Cloud — connect if configured
    cloud_url = os.getenv("COGNEE_CLOUD_URL")
    cloud_key = os.getenv("COGNEE_CLOUD_API_KEY")
    if cloud_url and cloud_key:
        try:
            import cognee
            await cognee.serve(url=cloud_url, api_key=cloud_key)
            logger.info(f"[Config] Cognee Cloud connected: {cloud_url}")
        except Exception as exc:
            logger.warning(f"[Config] Cognee Cloud connection failed (will use local): {exc}")

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

# CORS — explicit origins for dev + production
ALLOWED_ORIGINS = [
    "http://localhost:8081",
    "http://localhost:19006",
    "http://127.0.0.1:8081",
    "http://127.0.0.1:19006",
    "https://spillthereel-caa31.web.app",
    "https://spillthereel-caa31.firebaseapp.com",
    "https://trans-dash-waves-cameras.trycloudflare.com",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
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
