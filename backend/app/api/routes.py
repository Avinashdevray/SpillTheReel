"""
app/api/routes.py — API endpoints for SpillTheReel.

Endpoints:
  POST /ingest   — Accept a reel URL, kick off background multimodal pipeline.
  GET  /chat     — Query the Cognee knowledge graph with natural language.

Pipeline order (background task):
  1. download_video       — yt-dlp + cookies.txt → local MP4 + temp dir handle
  2. transcribe_audio     — Groq Whisper → plain-text transcript
  3. extract_visual_context — Gemini 1.5 Flash → visual summary
  4. generate_unified_summary — Groq Llama 3.3 → merged cohesive paragraph
  5. save_to_memory        — Cognee → Neo4j knowledge graph
  [cleanup] tmpdir.cleanup() — always executed in a finally block
"""

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.services.ingestion import download_video, transcribe_audio
from app.services.visual_audio import extract_visual_context
from app.services.brain import generate_unified_summary, save_to_memory, query_memory

logger = logging.getLogger("spillthereel.routes")

router = APIRouter()


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
# Background multimodal pipeline
# ---------------------------------------------------------------------------

async def _run_ingest_pipeline(url: str) -> None:
    """
    Full multimodal background pipeline:
      1. Download video (MP4) via yt-dlp + cookies.txt.
      2. Transcribe audio with Groq Whisper.
      3. Extract visual context with Gemini 1.5 Flash.
      4. Merge into a unified summary with Groq Llama 3.3.
      5. Persist the summary to Cognee / Neo4j.

    All errors are caught and logged to stderr with their specific type.
    The local temp directory is ALWAYS cleaned up in the finally block.
    This function must NOT raise — BackgroundTasks silently drops exceptions.
    """
    logger.info(f"[Pipeline] ▶ Starting multimodal ingestion for: {url}")

    # ------------------------------------------------------------------
    # Step 1: Download video — obtain temp dir handle for explicit cleanup
    # ------------------------------------------------------------------
    try:
        video_path, tmpdir = await download_video(url)
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
        # Step 3: Extract visual context with Gemini 1.5 Flash
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
        # Step 5: Save to Cognee knowledge graph
        # ------------------------------------------------------------------
        logger.info(f"[Pipeline] [5/5] Saving to Cognee knowledge graph: {url}")
        try:
            await save_to_memory(url=url, unified_summary=unified_summary)
            logger.info(f"[Pipeline] ✅ Successfully memorized: {url}")
        except ConnectionError as exc:
            logger.error(
                f"[DatabaseConnectionError] Neo4j unreachable while saving '{url}'. "
                f"Details: {exc}",
                exc_info=True,
            )
        except Exception as exc:
            logger.error(
                f"[MemoryError:{type(exc).__name__}] Failed to store summary for '{url}'. "
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
async def ingest_reel(req: IngestRequest, background_tasks: BackgroundTasks):
    """
    Accept a reel/video URL and asynchronously process it via the multimodal pipeline.

    Returns immediately with an acknowledgement. All processing (download,
    transcription, visual extraction, graph storage) happens in the background.
    Monitor server logs (stderr) for step-by-step progress.
    """
    if not req.url or not req.url.strip():
        raise HTTPException(status_code=422, detail="url field must not be empty.")

    background_tasks.add_task(_run_ingest_pipeline, req.url.strip())
    logger.info(f"[Ingest] ✉ Queued multimodal pipeline for: {req.url}")
    return IngestResponse(
        status="processing",
        message=(
            f"Reel '{req.url}' is being processed (download → transcribe → "
            "visual extract → summarise → memorise). Check server logs for progress."
        ),
    )


@router.get("/chat", response_model=ChatResponse, tags=["Query"])
async def chat_query(q: Optional[str] = None):
    """
    Query the Cognee knowledge graph with a natural language question.

    The graph contains unified multimodal summaries (audio + visual) of all
    ingested reels, so questions about on-screen text, objects, or actions
    are fully supported.

    GUARANTEE: This endpoint ALWAYS returns HTTP 200. Errors are surfaced
    as a friendly string inside the JSON `response` field, never as 4xx/5xx.
    """
    if not q or not q.strip():
        raise HTTPException(
            status_code=422,
            detail="Query parameter 'q' must not be empty.",
        )

    question = q.strip()
    logger.info(f"[Chat] Received query: '{question}'")

    try:
        results = await query_memory(question)
    except ConnectionError as exc:
        logger.error(
            f"[DatabaseConnectionError] Neo4j unreachable during query. Details: {exc}",
            exc_info=True,
        )
        return ChatResponse(
            query=question,
            response="The knowledge graph is temporarily unavailable. Please try again in a moment.",
        )
    except Exception as exc:
        logger.error(
            f"[QueryError:{type(exc).__name__}] Unexpected error querying memory. Details: {exc}",
            exc_info=True,
        )
        return ChatResponse(
            query=question,
            response="Something went wrong while searching. Please try again or re-ingest the Reel.",
        )

    # Handle the empty-graph sentinel returned by brain.py
    if results == "__EMPTY_GRAPH__":
        logger.info(f"[Chat] Empty graph sentinel received for query: '{question}'")
        return ChatResponse(
            query=question,
            response=(
                "My memory is empty! Please add a Reel first using the /ingest endpoint, "
                "then ask me again."
            ),
        )

    return ChatResponse(query=question, response=results)
