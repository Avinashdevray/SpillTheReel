"""
app/api/routes.py — API endpoints for SpillTheReel.

Endpoints:
  POST /ingest   — Accept a reel URL, kick off background multimodal pipeline.
  GET  /chat     — Query the user-isolated database with keyword search.
  GET  /share-target — Share sheet landing route from Instagram.
"""

import logging
import asyncio
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
import firebase_admin
from firebase_admin import auth as firebase_auth

from app.services.ingestion import download_video, transcribe_audio
from app.services.visual_audio import extract_visual_context
from app.services.brain import generate_unified_summary, save_to_memory
from app.services.repository import get_neo4j_driver, GraphRepository

logger = logging.getLogger("spillthereel.routes")

router = APIRouter()

REEL_PATTERN = re.compile(r'https?://(?:www\.)?instagram\.com/(?:reel|reels|p)/[A-Za-z0-9_-]+/?[^\s&]*')

# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class IngestRequest(BaseModel):
    """Payload for the /ingest endpoint."""
    url: str  # Plain str to accommodate both full HTTP URLs and short-codes


class IngestResponse(BaseModel):
    status: str
    message: str


class ChatResponse(BaseModel):
    query: str
    response: object


# ---------------------------------------------------------------------------
# Authentication Dependencies
# ---------------------------------------------------------------------------

async def get_current_uid(request: Request) -> str:
    """Dependency to extract and verify the Firebase ID Token from headers or cookies."""
    token = request.cookies.get("session") or request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        raise HTTPException(status_code=401, detail="Authentication token is missing. Please log in.")
    try:
        decoded = firebase_auth.verify_id_token(token)
        return decoded["uid"]
    except Exception as exc:
        logger.error(f"[AuthError] Token verification failed: {exc}")
        raise HTTPException(status_code=401, detail=f"Invalid or expired credentials: {exc}")


def get_repo(uid: str = Depends(get_current_uid)) -> GraphRepository:
    """Dependency to instantiate the GraphRepository bound to the current user's UID."""
    driver = get_neo4j_driver()
    return GraphRepository(driver, uid)


# ---------------------------------------------------------------------------
# Background multimodal pipeline
# ---------------------------------------------------------------------------

async def _run_ingest_pipeline(url: str, uid: str) -> None:
    """
    Full multimodal background pipeline:
      1. Download video (MP4) via yt-dlp + cookies.txt.
      2. Transcribe audio with Groq Whisper.
      3. Extract visual context with Gemini 1.5 Flash.
      4. Merge into a unified summary with Groq Llama 3.3.
      5. Persist to Cognee knowledge graph and user-isolated Neo4j DB.

    All errors are caught and logged to stderr with their specific type.
    The local temp directory is ALWAYS cleaned up in the finally block.
    This function must NOT raise — BackgroundTasks silently drops exceptions.
    """
    logger.info(f"[Pipeline] ▶ Starting user-isolated ingestion for: {url} (user: {uid})")

    # ------------------------------------------------------------------
    # Step 1: Download video — obtain temp dir handle for explicit cleanup
    # ------------------------------------------------------------------
    try:
        video_path, tmpdir, metadata = await download_video(url)
    except FileNotFoundError as exc:
        logger.error(
            f"[AuthenticationError] cookies.txt missing — cannot download '{url}'. "
            f"Details: {exc}",
            exc_info=True,
        )
        return
    except ConnectionError as exc:
        logger.error(
            f"[NetworkError] Network failure while downloading '{url}'. Details: {exc}",
            exc_info=True,
        )
        return
    except RuntimeError as exc:
        logger.error(
            f"[DownloadError] yt-dlp failed for '{url}'. Details: {exc}",
            exc_info=True,
        )
        return
    except Exception as exc:
        logger.error(
            f"[UnexpectedError:{type(exc).__name__}] Download failed for '{url}'. "
            f"Details: {exc}",
            exc_info=True,
        )
        return

    # tmpdir is alive — wrap everything else in try/finally to guarantee cleanup
    try:
        # ------------------------------------------------------------------
        # Step 2: Transcribe audio with Groq Whisper
        # ------------------------------------------------------------------
        logger.info(f"[Pipeline] [2/5] Transcribing audio: {url}")
        try:
            transcript = await transcribe_audio(video_path)
        except RuntimeError as exc:
            logger.error(
                f"[TranscriptionError] Groq Whisper failed for '{url}'. Details: {exc}",
                exc_info=True,
            )
            return

        # ------------------------------------------------------------------
        # Step 3: Extract visual context with Gemini 1.5/2.0 Flash
        # ------------------------------------------------------------------
        logger.info(f"[Pipeline] [3/5] Extracting visual context via Gemini: {url}")
        try:
            visual_context = await extract_visual_context(video_path)
        except RuntimeError as exc:
            logger.error(
                f"[GeminiError] Visual extraction failed for '{url}'. Details: {exc}",
                exc_info=True,
            )
            # Degrade gracefully: continue with transcript-only if Gemini fails
            logger.warning(
                f"[Pipeline] Degrading to audio-only mode for '{url}' due to Gemini failure."
            )
            visual_context = "[Visual context unavailable — Gemini extraction failed]"

        # ------------------------------------------------------------------
        # Step 4: Generate unified multimodal summary
        # ------------------------------------------------------------------
        logger.info(f"[Pipeline] [4/5] Generating unified summary: {url}")
        try:
            unified_summary = await generate_unified_summary(
                audio_transcript=transcript,
                visual_context=visual_context,
            )
        except RuntimeError as exc:
            logger.error(
                f"[SummaryError] Groq merge step failed for '{url}'. Details: {exc}",
                exc_info=True,
            )
            # Degrade gracefully: use raw transcript as fallback summary
            logger.warning(
                f"[Pipeline] Falling back to raw transcript for '{url}'."
            )
            unified_summary = transcript

        # ------------------------------------------------------------------
        # Step 5: Save to Cognee and Neo4j User isolated structure
        # ------------------------------------------------------------------
        logger.info(f"[Pipeline] [5/5] Saving to Cognee knowledge graph and Neo4j for user {uid}: {url}")
        try:
            # 1. Save to Cognee graph (global search, entities if available)
            await save_to_memory(url=url, unified_summary=unified_summary)
        except Exception as exc:
            logger.warning(f"[Pipeline] Cognee save warning (non-fatal): {exc}")

        try:
            # 2. Save directly to User node and isolated Reel node in Neo4j
            driver = get_neo4j_driver()
            repo = GraphRepository(driver, uid)
            repo.save_reel(
                url=url, 
                transcript=transcript, 
                summary=unified_summary,
                author=metadata.get("author", ""),
                thumbnail=metadata.get("thumbnail", "")
            )
            logger.info(f"[Pipeline] ✅ Successfully memorized in user-isolated graph: {url}")
        except ConnectionError as exc:
            logger.error(
                f"[DatabaseConnectionError] Neo4j unreachable while saving user isolated '{url}'. "
                f"Details: {exc}",
                exc_info=True,
            )
        except Exception as exc:
            logger.error(
                f"[MemoryError:{type(exc).__name__}] Failed to store isolated summary for '{url}'. "
                f"Details: {exc}",
                exc_info=True,
            )

    finally:
        # ------------------------------------------------------------------
        # Cleanup: always remove the local temp directory
        # ------------------------------------------------------------------
        try:
            tmpdir.cleanup()
            logger.info(f"[Pipeline] 🧹 Temp directory cleaned up for: {url}")
        except Exception as exc:
            logger.warning(f"[Pipeline] Could not clean temp dir (non-fatal): {exc}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/ingest", response_model=IngestResponse, tags=["Ingestion"])
async def ingest_reel(req: IngestRequest, repo: GraphRepository = Depends(get_repo)):
    """
    Accept a reel/video URL and asynchronously process it via the user-isolated pipeline.

    Returns immediately with an acknowledgement.
    """
    if not req.url or not req.url.strip():
        raise HTTPException(status_code=422, detail="url field must not be empty.")

    url_str = req.url.strip()
    asyncio.create_task(_run_ingest_pipeline(url_str, repo.uid))
    logger.info(f"[Ingest] ✉ Queued user-isolated pipeline for: {url_str} (user: {repo.uid})")
    return IngestResponse(
        status="processing",
        message=(
            f"Reel '{url_str}' is being processed (download → transcribe → "
            "visual extract → summarise → memorise). Check server logs for progress."
        ),
    )


@router.get("/chat", response_model=ChatResponse, tags=["Query"])
async def chat_query(q: Optional[str] = None, repo: GraphRepository = Depends(get_repo)):
    """
    Query the user-isolated Neo4j database with a keyword.
    """
    if not q or not q.strip():
        raise HTTPException(
            status_code=422,
            detail="Query parameter 'q' must not be empty.",
        )

    question = q.strip()
    logger.info(f"[Chat] Received query: '{question}' for user {repo.uid}")

    try:
        results = repo.query_reels(question)
    except ConnectionError as exc:
        logger.error(
            f"[DatabaseConnectionError] Neo4j unreachable during query. Details: {exc}",
            exc_info=True,
        )
        return ChatResponse(
            query=question,
            response={"text": "The knowledge graph is temporarily unavailable. Please try again in a moment.", "reels": []},
        )
    except Exception as exc:
        logger.error(
            f"[QueryError:{type(exc).__name__}] Unexpected error querying memory. Details: {exc}",
            exc_info=True,
        )
        return ChatResponse(
            query=question,
            response={"text": "Something went wrong while searching. Please try again or re-ingest the Reel.", "reels": []},
        )

    if not results:
        # Check if the user has any reels at all
        try:
            all_reels = repo.get_all_reels()
            if not all_reels:
                return ChatResponse(
                    query=question,
                    response={
                        "text": "My memory is empty! Please add a Reel first using the /ingest endpoint, then ask me again.",
                        "reels": []
                    }
                )
        except Exception:
            pass
        return ChatResponse(
            query=question,
            response={"text": "I couldn't find any reels matching that query in your collection.", "reels": []}
        )

    # Use the top result only
    top_reel = results[0]
    
    # Generate a conversational answer based on the top reel
    from app.services.brain import generate_chat_answer
    answer = await generate_chat_answer(question, top_reel)

    response_data = {
        "text": answer,
        "reels": [top_reel]
    }

    return ChatResponse(query=question, response=response_data)


@router.get("/share-target")
async def share_target(request: Request, background_tasks: BackgroundTasks, repo: GraphRepository = Depends(get_repo)):
    """
    Instagram share sheet Web Share Target landing endpoint.
    Extracts Reel URL from url or text parameters, queues the ingestion task,
    and redirects the client to the frontend home.
    """
    params = request.query_params
    print("SHARE TARGET RECEIVED:", dict(params))

    candidate = params.get("url", "") + " " + params.get("text", "")
    match = REEL_PATTERN.search(candidate)

    if match:
        background_tasks.add_task(_run_ingest_pipeline, match.group(0), repo.uid)
        return RedirectResponse(url="/?saved=1")

    return RedirectResponse(url="/?error=no_reel_found")
