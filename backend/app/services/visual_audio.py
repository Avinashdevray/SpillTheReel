"""
app/services/visual_audio.py — Gemini 1.5 Flash visual context extraction service.

Uses the NEW `google-genai` SDK (google.genai), NOT the deprecated
`google-generativeai` (google.generativeai) package.

Responsibilities:
  - Upload a local video file to the Gemini Files API.
  - Poll until the file state transitions from PROCESSING → ACTIVE.
  - Generate a structured visual summary (on-screen text, objects, actions).
  - Delete the uploaded file from Gemini servers after use (guardrail).
  - Fall back to Bluesmind (gpt-4o vision) when Gemini quota is exhausted.

Design constraints:
  - The genai.Client is instantiated INSIDE each function — never at module level.
  - Raises RuntimeError with a clear label on any Gemini-side failure.
  - _safe_delete() suppresses all errors — cleanup never crashes the pipeline.
"""

import os
import re
import asyncio
import subprocess
import base64
import logging

import httpx

logger = logging.getLogger("spillthereel.visual")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GEMINI_MODEL = "gemini-2.0-flash"
_POLL_INTERVAL_SECONDS = 3
_POLL_MAX_ATTEMPTS = 40          # 40 × 3 s = 2-minute timeout
_VISUAL_PROMPT = """\
You are analyzing a short-form video (Reel / TikTok / YouTube Short).
Provide a concise but thorough summary covering:

1. ON-SCREEN TEXT — any captions, subtitles, labels, overlays, or graphics visible.
2. OBJECTS & SCENE — key objects, settings, and visual elements present.
3. ACTIONS & EVENTS — what is happening, step-by-step if applicable (e.g., recipe steps, workout reps).

Be specific and literal. Do not infer or guess beyond what is visually present.
Format your response as plain prose (no bullet points or markdown headers).
"""

_BLUESMIND_ENDPOINT = "https://api.bluesminds.com/v1/"
_FRAMES_TO_EXTRACT = 3


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def extract_visual_context(video_path: str) -> str:
    """
    Upload *video_path* to Gemini Files API and generate a visual summary.

    Uses the `google-genai` SDK (from google import genai).
    The client is created INSIDE this function to prevent module-level crashes.

    Args:
        video_path: Absolute path to the locally downloaded MP4 file.

    Returns:
        A plain-text visual summary string.

    Raises:
        RuntimeError: On missing API key, upload failure, polling timeout,
                      or generation failure.
    """
    from google import genai                        # new SDK — deferred import
    from google.genai import types as genai_types  # for FileState enum

    bluesmind_key = os.getenv("BLUESMIND")
    if bluesmind_key:
        logger.info("[Visual] Using Bluesmind (gpt-4o) for visual extraction.")
        return await _extract_via_bluesmind(video_path, bluesmind_key)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "[ConfigurationError] GEMINI_API_KEY environment variable is not set. "
            "Add it to backend/.env."
        )

    # Client is created here — NOT at module level
    client = genai.Client(api_key=api_key)

    # ------------------------------------------------------------------
    # Step 1: Upload video to Gemini Files API
    # ------------------------------------------------------------------
    logger.info(f"[Visual] Uploading video to Gemini Files API: {video_path}")
    try:
        gemini_file = client.files.upload(
            file=video_path,
            config={"display_name": os.path.basename(video_path)},
        )
    except Exception as exc:
        raise RuntimeError(
            f"[GeminiUploadError] Failed to upload '{video_path}' to Gemini: {exc}"
        ) from exc

    logger.info(f"[Visual] Upload initiated. Gemini file name: {gemini_file.name}")

    # ------------------------------------------------------------------
    # Step 2: Poll until file state is ACTIVE
    # ------------------------------------------------------------------
    logger.info("[Visual] Polling Gemini for file processing state...")
    file_ref = gemini_file  # will be refreshed each iteration

    for attempt in range(1, _POLL_MAX_ATTEMPTS + 1):
        try:
            file_ref = client.files.get(name=gemini_file.name)
        except Exception as exc:
            raise RuntimeError(
                f"[GeminiPollError] Failed to poll file status on attempt {attempt}: {exc}"
            ) from exc

        # file_ref.state is a FileState enum; .name gives the string value
        # The google-genai SDK returns short names ('ACTIVE', 'PROCESSING', 'FAILED')
        state = file_ref.state.name
        logger.info(f"[Visual] Poll {attempt}/{_POLL_MAX_ATTEMPTS} — state: {state}")

        if state == "ACTIVE":
            logger.info("[Visual] File is ACTIVE. Proceeding to generation.")
            break
        elif state == "FAILED":
            _safe_delete(client, gemini_file.name)
            raise RuntimeError(
                f"[GeminiProcessingError] Gemini reported FAILED state for '{video_path}'. "
                "The video may be corrupt or in an unsupported format."
            )

        if attempt == _POLL_MAX_ATTEMPTS:
            _safe_delete(client, gemini_file.name)
            raise RuntimeError(
                f"[GeminiTimeoutError] File did not become ACTIVE within "
                f"{_POLL_MAX_ATTEMPTS * _POLL_INTERVAL_SECONDS}s for '{video_path}'."
            )

        await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    # ------------------------------------------------------------------
    # Step 3: Generate visual context
    # ------------------------------------------------------------------
    logger.info(f"[Visual] Generating visual context with Gemini {_GEMINI_MODEL}...")
    try:
        response = client.models.generate_content(
            model=_GEMINI_MODEL,
            contents=[file_ref, _VISUAL_PROMPT],
        )
        visual_summary = response.text
        _safe_delete(client, gemini_file.name)
        logger.info(f"[Visual] Visual summary preview: {visual_summary[:200]}...")
        return visual_summary
    except Exception as exc:
        _safe_delete(client, gemini_file.name)
        exc_msg = str(exc)
        if "429" in exc_msg or "RESOURCE_EXHAUSTED" in exc_msg or "quota" in exc_msg.lower():
            bluesmind_key = os.getenv("BLUESMIND")
            if bluesmind_key:
                logger.warning("[Visual] Gemini quota exhausted. Falling back to Bluesmind vision...")
                try:
                    return await _extract_via_bluesmind(video_path, bluesmind_key)
                except Exception as fallback_exc:
                    logger.warning(f"[Visual] Lightning AI fallback also failed: {fallback_exc}")
        raise RuntimeError(
            f"[GeminiGenerationError] Content generation failed for '{video_path}': {exc}"
        ) from exc


def delete_gemini_file(gemini_file_name: str) -> None:
    """
    Explicitly delete a file from Gemini's servers by its resource name.

    Exposed as a public helper so callers can trigger cleanup even if
    extract_visual_context raised before completing its own cleanup.

    Args:
        gemini_file_name: The `name` attribute of the Gemini file object
                          (e.g., 'files/abc123').
    """
    from google import genai
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("[Visual] Cannot delete Gemini file — GEMINI_API_KEY not set.")
        return
    client = genai.Client(api_key=api_key)
    _safe_delete(client, gemini_file_name)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_delete(client, gemini_file_name: str) -> None:
    """
    Attempt to delete a Gemini-hosted file, suppressing all errors.

    Errors are logged as warnings — deletion failure must never crash the pipeline.

    Args:
        client:            An authenticated genai.Client instance.
        gemini_file_name:  The resource name (e.g. 'files/abc123').
    """
    try:
        client.files.delete(name=gemini_file_name)
        logger.info(f"[Visual] Deleted Gemini file: {gemini_file_name}")
    except Exception as exc:
        logger.warning(
            f"[Visual] Could not delete Gemini file '{gemini_file_name}' (non-fatal): {exc}"
        )


# ---------------------------------------------------------------------------
# Bluesmind fallback — OpenAI-compatible vision proxy
# ---------------------------------------------------------------------------

async def _extract_via_bluesmind(video_path: str, api_key: str) -> str:
    """
    Fallback visual extraction using Bluesmind's OpenAI-compatible endpoint.

    Extracts a few key frames from the video via ffmpeg and sends them as
    base64 images to the chat completions API (gpt-4o vision).

    Args:
        video_path: Absolute path to the local video file.
        api_key:    BLUESMIND API key.

    Returns:
        A plain-text visual summary string.

    Raises:
        RuntimeError: If frame extraction or the API call fails.
    """
    frames = _extract_frames(video_path)
    if not frames:
        raise RuntimeError(
            f"[BluesmindFallbackError] No frames could be extracted from '{video_path}'"
        )

    content_parts = [{"type": "text", "text": _VISUAL_PROMPT}]
    for frame_path in frames:
        with open(frame_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })

    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": content_parts}],
        "max_tokens": 1024,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{_BLUESMIND_ENDPOINT}chat/completions",
            headers=headers,
            json=payload,
        )

    if resp.status_code != 200:
        body = resp.text[:300]
        raise RuntimeError(
            f"[BluesmindFallbackError] API returned {resp.status_code}: {body}"
        )

    data = resp.json()
    visual_summary = data["choices"][0]["message"]["content"].strip()
    logger.info(f"[Visual] Bluesmind summary preview: {visual_summary[:200]}...")

    for f in frames:
        _unlink_safe(f)

    return visual_summary


def _extract_frames(video_path: str) -> list[str]:
    """
    Extract *n* evenly-spaced JPEG frames from *video_path* using ffmpeg.

    Returns a list of paths to the extracted frame images.
    """
    import math

    # Get video duration
    try:
        dur_result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                video_path,
            ],
            capture_output=True, text=True, check=True,
        )
        duration = float(dur_result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError) as exc:
        raise RuntimeError(
            f"[FrameExtractionError] Could not determine video duration: {exc}"
        ) from exc

    if duration <= 0:
        raise RuntimeError(
            f"[FrameExtractionError] Invalid video duration: {duration}"
        )

    base = os.path.splitext(video_path)[0]
    timestamps = [
        duration * (i + 1) / (_FRAMES_TO_EXTRACT + 1)
        for i in range(_FRAMES_TO_EXTRACT)
    ]
    frame_paths = []

    for idx, ts in enumerate(timestamps):
        out_path = f"{base}_frame{idx}.jpg"
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", str(ts),
                    "-i", video_path,
                    "-vframes", "1",
                    "-q:v", "2",
                    str(out_path),
                ],
                capture_output=True, check=True,
            )
            frame_paths.append(out_path)
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
            logger.warning(
                f"[Visual] Failed to extract frame at {ts}s (non-fatal): {stderr[:200]}"
            )

    return frame_paths


def _unlink_safe(path: str) -> None:
    """Remove a file, suppressing errors."""
    try:
        os.unlink(path)
    except Exception:
        pass
