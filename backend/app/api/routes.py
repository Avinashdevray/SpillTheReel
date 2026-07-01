"""
SpillTheReel – API Routes

Defines the /ingest and /search endpoints.
"""

from fastapi import APIRouter, HTTPException, status

from app.models.schemas import (
    ReelIngestRequest,
    UnifiedVideoPayload,
    SearchQuery,
    SearchResult,
)
from app.services.ingestion import download_video
from app.services.visual_audio import process_video
from app.services.brain import store_in_memory, query_memory

# ── Routers ───────────────────────────────────────────────────────────────────
ingest_router = APIRouter()
search_router = APIRouter()


@ingest_router.post(
    "/",
    response_model=UnifiedVideoPayload,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a video URL",
)
async def ingest_video(request: ReelIngestRequest) -> UnifiedVideoPayload:
    """
    Full ingestion pipeline:
    1. Download video via yt-dlp
    2. Run transcription, scene detection, OCR
    3. Store unified payload in Cognee graph memory
    """
    # Step 1 – Download
    download_result = await download_video(request.url)
    if download_result is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to download video from URL: {request.url}",
        )

    # Step 2 – Process (transcription, scene detect, OCR)
    payload: UnifiedVideoPayload = await process_video(
        file_path=download_result,
        source_url=str(request.url),
        tags=request.tags,
    )

    # Step 3 – Store in Cognee
    await store_in_memory(payload)

    return payload


@search_router.post(
    "/",
    response_model=list[SearchResult],
    summary="Search the knowledge graph",
)
async def search_knowledge(query: SearchQuery) -> list[SearchResult]:
    """Semantic search across the Cognee knowledge graph."""
    results = await query_memory(query.query, top_k=query.top_k)
    return results
