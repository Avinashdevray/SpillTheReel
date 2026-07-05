"""
app/api/routes.py — API endpoints for SpillTheReel.
"""

import logging
import asyncio
import re
import time
import uuid
from typing import Optional
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Depends, Request
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
# In-memory job tracking
# ---------------------------------------------------------------------------
_job_store: dict[str, dict] = {}
_job_lock = asyncio.Lock()

async def _track_job(job_id: str, status: str, message: str = "") -> dict:
    async with _job_lock:
        _job_store[job_id] = {
            "status": status,
            "message": message,
            "updated_at": time.time(),
        }
        return _job_store[job_id]

async def _get_job(job_id: str) -> Optional[dict]:
    async with _job_lock:
        return _job_store.get(job_id)

# ---------------------------------------------------------------------------
# In-memory rate limiter (per-UID, 10 requests / 60s)
# ---------------------------------------------------------------------------
_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_rate_limit_lock = asyncio.Lock()
_RATE_LIMIT = 10
_RATE_WINDOW = 60

async def _check_rate_limit(uid: str) -> bool:
    now = time.time()
    window_start = now - _RATE_WINDOW
    async with _rate_limit_lock:
        timestamps = _rate_limit_store[uid]
        timestamps[:] = [t for t in timestamps if t > window_start]
        if len(timestamps) >= _RATE_LIMIT:
            return False
        timestamps.append(now)
        return True

# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class IngestRequest(BaseModel):
    url: str

class IngestResponse(BaseModel):
    status: str
    message: str
    job_id: str = ""

class ChatResponse(BaseModel):
    query: str
    response: object

class StatusResponse(BaseModel):
    job_id: str
    status: str
    message: str
    updated_at: float

# ---------------------------------------------------------------------------
# Authentication Dependencies
# ---------------------------------------------------------------------------

async def get_current_uid(request: Request) -> str:
    cookie_token = request.cookies.get("session")
    header_token = request.headers.get("Authorization", "").replace("Bearer ", "")

    token = header_token or cookie_token
    if not token:
        raise HTTPException(status_code=401, detail="Authentication token is missing. Please log in.")

    try:
        if cookie_token:
            decoded = firebase_auth.verify_session_cookie(cookie_token, check_revoked=False)
        else:
            decoded = firebase_auth.verify_id_token(header_token)
        return decoded["uid"]
    except Exception as exc:
        logger.error(f"[AuthError] Token verification failed: {exc}")
        raise HTTPException(status_code=401, detail="Invalid or expired credentials. Please log in again.")


def get_repo(uid: str = Depends(get_current_uid)) -> GraphRepository:
    driver = get_neo4j_driver()
    return GraphRepository(driver, uid)


# ---------------------------------------------------------------------------
# Background multimodal pipeline
# ---------------------------------------------------------------------------

async def _run_ingest_pipeline(url: str, uid: str, job_id: str) -> None:
    logger.info(f"[Pipeline] Starting ingestion for: {url} (user: {uid}, job: {job_id})")
    await _track_job(job_id, "downloading", "Downloading video from Instagram...")

    try:
        video_path, tmpdir, metadata = await download_video(url)
    except (FileNotFoundError, ConnectionError, RuntimeError) as exc:
        await _track_job(job_id, "failed", str(exc))
        return
    except Exception as exc:
        await _track_job(job_id, "failed", f"Unexpected download error: {exc}")
        return

    try:
        await _track_job(job_id, "transcribing", "Transcribing audio with Whisper...")
        try:
            transcript = await transcribe_audio(video_path)
        except Exception as exc:
            await _track_job(job_id, "failed", f"Transcription failed: {exc}")
            return

        await _track_job(job_id, "extracting_visuals", "Analyzing visual content...")
        try:
            visual_context = await extract_visual_context(video_path)
        except Exception as exc:
            logger.warning(f"[Pipeline] Degrading to audio-only for '{url}': {exc}")
            visual_context = "[Visual context unavailable]"

        await _track_job(job_id, "summarizing", "Generating unified summary...")
        try:
            unified_summary = await generate_unified_summary(
                audio_transcript=transcript,
                visual_context=visual_context,
            )
        except Exception as exc:
            logger.warning(f"[Pipeline] Falling back to raw transcript: {exc}")
            unified_summary = transcript

        await _track_job(job_id, "saving", "Saving to memory...")
        try:
            await save_to_memory(url=url, unified_summary=unified_summary, uid=uid)
        except Exception as exc:
            logger.warning(f"[Pipeline] Cognee save warning (non-fatal): {exc}")

        try:
            driver = get_neo4j_driver()
            repo = GraphRepository(driver, uid)
            repo.save_reel(
                url=url,
                transcript=transcript,
                summary=unified_summary,
                author=metadata.get("author", ""),
                thumbnail=metadata.get("thumbnail", "")
            )
            logger.info(f"[Pipeline] Saved to user-isolated graph: {url}")
        except Exception as exc:
            logger.error(f"[Pipeline] Neo4j save failed: {exc}", exc_info=True)

        await _track_job(job_id, "completed", "Reel processed and indexed successfully.")
        logger.info(f"[Pipeline] Completed: {url}")
    finally:
        try:
            tmpdir.cleanup()
        except Exception as exc:
            logger.warning(f"[Pipeline] Temp cleanup warning: {exc}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/ingest", response_model=IngestResponse, tags=["Ingestion"])
async def ingest_reel(req: IngestRequest, repo: GraphRepository = Depends(get_repo)):
    if not req.url or not req.url.strip():
        raise HTTPException(status_code=422, detail="url field must not be empty.")

    url_str = req.url.strip()
    if not REEL_PATTERN.match(url_str):
        raise HTTPException(
            status_code=422,
            detail="Invalid Instagram Reel URL. Must be an instagram.com/reel/..., /reels/..., or /p/... URL."
        )

    if not await _check_rate_limit(repo.uid):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please wait before submitting another reel.")

    job_id = f"ingest_{repo.uid}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    await _track_job(job_id, "queued", "Pipeline queued, starting shortly...")
    asyncio.create_task(_run_ingest_pipeline(url_str, repo.uid, job_id))

    logger.info(f"[Ingest] Queued pipeline job {job_id} for: {url_str} (user: {repo.uid})")
    return IngestResponse(
        status="processing",
        message="Reel is being processed (download → transcribe → visual extract → summarise → memorise).",
        job_id=job_id,
    )


@router.get("/status/{job_id}", response_model=StatusResponse, tags=["Ingestion"])
async def get_job_status(job_id: str, repo: GraphRepository = Depends(get_repo)):
    if not job_id.startswith(f"ingest_{repo.uid}"):
        raise HTTPException(status_code=404, detail="Job not found.")
    job = await _get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return StatusResponse(job_id=job_id, **job)


@router.get("/chat", response_model=ChatResponse, tags=["Query"])
async def chat_query(q: Optional[str] = None, repo: GraphRepository = Depends(get_repo)):
    if not q or not q.strip():
        raise HTTPException(status_code=422, detail="Query parameter 'q' must not be empty.")

    question = q.strip()
    logger.info(f"[Chat] Query: '{question}' for user {repo.uid}")

    if not await _check_rate_limit(repo.uid):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please wait before querying again.")

    # Try Cognee Cloud search first (falls back gracefully if not configured)
    from app.services.brain import query_memory
    try:
        cognee_results = await query_memory(question, repo.uid)
    except Exception as exc:
        logger.warning(f"[Chat] Cognee search error: {exc}")
        cognee_results = None

    if cognee_results and cognee_results != "__EMPTY_GRAPH__":
        neo4j_results = repo.query_reels(question)
        if neo4j_results:
            from app.services.brain import generate_chat_answer
            answer = await generate_chat_answer(question, neo4j_results[0])
            return ChatResponse(
                query=question,
                response={"text": answer, "reels": neo4j_results}
            )
        # Cognee Cloud found results but Neo4j has no data (e.g. driver was down during save)
        cognee_text = cognee_results[0].get("text", "") if isinstance(cognee_results, list) else ""
        if cognee_text:
            return ChatResponse(
                query=question,
                response={"text": cognee_text, "reels": []}
            )

    # Neo4j FULLTEXT keyword search (fallback)
    try:
        results = repo.query_reels(question)
    except Exception as exc:
        logger.error(f"[QueryError] Query failed: {exc}", exc_info=True)
        return ChatResponse(
            query=question,
            response={"text": "Something went wrong while searching. Please try again.", "reels": []},
        )

    if not results:
        try:
            all_reels = repo.get_all_reels()
            if not all_reels:
                return ChatResponse(
                    query=question,
                    response={
                        "text": "My memory is empty! Please add a Reel first using the /ingest endpoint.",
                        "reels": []
                    }
                )
        except Exception as exc:
            logger.warning(f"[Chat] Failed to check reels: {exc}")
        return ChatResponse(
            query=question,
            response={"text": "I couldn't find any reels matching that query in your collection.", "reels": []}
        )

    top_reel = results[0]
    from app.services.brain import generate_chat_answer
    answer = await generate_chat_answer(question, top_reel)

    return ChatResponse(
        query=question,
        response={"text": answer, "reels": [top_reel]}
    )


@router.get("/share-target")
async def share_target(request: Request, repo: GraphRepository = Depends(get_repo)):
    params = request.query_params
    candidate = str(params.get("url", "")) + " " + str(params.get("text", ""))
    match = REEL_PATTERN.search(candidate)

    if match:
        url_str = match.group(0)
        job_id = f"ingest_{repo.uid}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        await _track_job(job_id, "queued", "Pipeline queued from share target.")
        asyncio.create_task(_run_ingest_pipeline(url_str, repo.uid, job_id))
        return RedirectResponse(url=f"/?saved=1&job_id={job_id}")

    return RedirectResponse(url="/?error=no_reel_found")
