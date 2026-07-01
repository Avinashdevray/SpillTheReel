"""
SpillTheReel – FastAPI Application Entry Point

Configures CORS, mounts API routers, and starts the uvicorn server.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import ingest_router, search_router

app = FastAPI(
    title="SpillTheReel API",
    description="AI-powered audio-visual second brain – multimodal ingestion & Cognee graph memory.",
    version="0.1.0",
)

# ---------------------------------------------------------------------------
# CORS – allow local dev origins (Vite, React Native, Flutter, emulators)
# ---------------------------------------------------------------------------
ALLOWED_ORIGINS: list[str] = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8081",      # React Native Metro
    "http://localhost:19006",     # Expo web
    "http://10.0.2.2:8000",      # Android emulator → host
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(ingest_router, prefix="/api/v1/ingest", tags=["Ingestion"])
app.include_router(search_router, prefix="/api/v1/search", tags=["Search"])


@app.get("/", tags=["Health"])
async def root() -> dict[str, str]:
    """Health-check / landing endpoint."""
    return {"status": "ok", "service": "SpillTheReel API"}


# ---------------------------------------------------------------------------
# Run with: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
