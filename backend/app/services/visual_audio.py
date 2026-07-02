"""
app/services/visual_audio.py — Gemini 1.5 Flash visual context extraction service.

Uses the NEW `google-genai` SDK (google.genai), NOT the deprecated
`google-generativeai` (google.generativeai) package.

Responsibilities:
  - Upload a local video file to the Gemini Files API.
  - Poll until the file state transitions from PROCESSING → ACTIVE.
  - Generate a structured visual summary (on-screen text, objects, actions).
  - Delete the uploaded file from Gemini servers after use (guardrail).

Design constraints:
  - The genai.Client is instantiated INSIDE each function — never at module level.
  - Raises RuntimeError with a clear label on any Gemini-side failure.
  - _safe_delete() suppresses all errors — cleanup never crashes the pipeline.
"""

import os
import time
import logging

logger = logging.getLogger("spillthereel.visual")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GEMINI_MODEL = "gemini-1.5-flash"
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
        state = file_ref.state.name   # 'FILE_STATE_ACTIVE' | 'FILE_STATE_PROCESSING' | 'FILE_STATE_FAILED'
        logger.info(f"[Visual] Poll {attempt}/{_POLL_MAX_ATTEMPTS} — state: {state}")

        if state == "FILE_STATE_ACTIVE":
            logger.info("[Visual] File is ACTIVE. Proceeding to generation.")
            break
        elif state == "FILE_STATE_FAILED":
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

        time.sleep(_POLL_INTERVAL_SECONDS)

    # ------------------------------------------------------------------
    # Step 3: Generate visual context
    # ------------------------------------------------------------------
    logger.info("[Visual] Generating visual context with Gemini 1.5 Flash...")
    try:
        response = client.models.generate_content(
            model=_GEMINI_MODEL,
            contents=[file_ref, _VISUAL_PROMPT],
        )
        visual_summary = response.text
    except Exception as exc:
        _safe_delete(client, gemini_file.name)
        raise RuntimeError(
            f"[GeminiGenerationError] Content generation failed for '{video_path}': {exc}"
        ) from exc

    logger.info(f"[Visual] Visual summary preview: {visual_summary[:200]}...")

    # ------------------------------------------------------------------
    # Step 4: Clean up file from Gemini servers (guardrail)
    # ------------------------------------------------------------------
    _safe_delete(client, gemini_file.name)

    return visual_summary


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
