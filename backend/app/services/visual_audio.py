"""
app/services/visual_audio.py — Gemini 2.0 Flash visual context extraction service.

Uses Gemini as the primary provider. Falls back to Bluesmind (mimo-v2.5 vision via
frame extraction) only when Gemini returns a 429 quota-exhausted error.

All blocking I/O (Gemini SDK calls, ffmpeg subprocess) is offloaded to
asyncio.to_thread to avoid freezing the event loop.
"""

import os
import asyncio
import subprocess
import base64
import logging

import httpx

logger = logging.getLogger("spillthereel.visual")

_GEMINI_MODEL = "gemini-2.0-flash"
_POLL_INTERVAL_SECONDS = 3
_POLL_MAX_ATTEMPTS = 40
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


async def extract_visual_context(video_path: str) -> str:
    if not video_path or not os.path.isfile(video_path):
        logger.warning("[Visual] No valid video file provided. Skipping visual extraction.")
        return ""

    from google import genai

    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        try:
            return await _extract_via_gemini(video_path, api_key)
        except RuntimeError as exc:
            exc_msg = str(exc)
            if "429" in exc_msg or "RESOURCE_EXHAUSTED" in exc_msg or "quota" in exc_msg.lower():
                bluesmind_key = os.getenv("BLUESMIND")
                if bluesmind_key:
                    logger.warning("[Visual] Gemini quota exhausted. Falling back to Bluesmind vision...")
                    try:
                        return await _extract_via_bluesmind(video_path, bluesmind_key)
                    except Exception as bluesmind_exc:
                        logger.error(f"[Visual] Bluesmind fallback also failed: {bluesmind_exc}. Proceeding without visual context.")
                        return ""
            logger.warning(f"[Visual] Gemini extraction failed (non-quota): {exc}. Proceeding without visual context.")
            return ""

    bluesmind_key = os.getenv("BLUESMIND")
    if bluesmind_key:
        logger.info("[Visual] No Gemini API key. Using Bluesmind (mimo-v2.5) for visual extraction.")
        try:
            return await _extract_via_bluesmind(video_path, bluesmind_key)
        except Exception as exc:
            logger.error(f"[Visual] Bluesmind extraction failed: {exc}. Proceeding without visual context.")
            return ""

    logger.warning("[Visual] No visual provider configured. Proceeding without visual context.")
    return ""


async def _extract_via_gemini(video_path: str, api_key: str) -> str:
    from google import genai

    client = genai.Client(api_key=api_key)

    logger.info(f"[Visual] Uploading video to Gemini Files API: {video_path}")
    try:
        gemini_file = await asyncio.to_thread(
            client.files.upload,
            file=video_path,
            config={"display_name": os.path.basename(video_path)},
        )
    except Exception as exc:
        raise RuntimeError(
            f"[GeminiUploadError] Failed to upload '{video_path}' to Gemini: {exc}"
        ) from exc

    logger.info(f"[Visual] Upload initiated. Gemini file name: {gemini_file.name}")

    logger.info("[Visual] Polling Gemini for file processing state...")
    file_ref = gemini_file
    for attempt in range(1, _POLL_MAX_ATTEMPTS + 1):
        try:
            file_ref = await asyncio.to_thread(client.files.get, name=gemini_file.name)
        except Exception as exc:
            await asyncio.to_thread(_safe_delete, client, gemini_file.name)
            raise RuntimeError(
                f"[GeminiPollError] Failed to poll file status: {exc}"
            ) from exc

        state = file_ref.state.name
        logger.info(f"[Visual] Poll {attempt}/{_POLL_MAX_ATTEMPTS} — state: {state}")

        if state == "ACTIVE":
            logger.info("[Visual] File is ACTIVE. Proceeding to generation.")
            break
        elif state == "FAILED":
            await asyncio.to_thread(_safe_delete, client, gemini_file.name)
            raise RuntimeError(
                f"[GeminiProcessingError] Gemini reported FAILED for '{video_path}'."
            )

        if attempt == _POLL_MAX_ATTEMPTS:
            await asyncio.to_thread(_safe_delete, client, gemini_file.name)
            raise RuntimeError(
                f"[GeminiTimeoutError] File did not become ACTIVE within "
                f"{_POLL_MAX_ATTEMPTS * _POLL_INTERVAL_SECONDS}s."
            )

        await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    logger.info(f"[Visual] Generating visual context with Gemini {_GEMINI_MODEL}...")
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=_GEMINI_MODEL,
            contents=[file_ref, _VISUAL_PROMPT],
        )
        visual_summary = response.text
        await asyncio.to_thread(_safe_delete, client, gemini_file.name)
        logger.info(f"[Visual] Gemini summary preview: {visual_summary[:200]}...")
        return visual_summary
    except Exception as exc:
        await asyncio.to_thread(_safe_delete, client, gemini_file.name)
        raise RuntimeError(
            f"[GeminiGenerationError] Content generation failed: {exc}"
        ) from exc


def delete_gemini_file(gemini_file_name: str) -> None:
    from google import genai
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return
    client = genai.Client(api_key=api_key)
    _safe_delete(client, gemini_file_name)


def _safe_delete(client, gemini_file_name: str) -> None:
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
    frames = await asyncio.to_thread(_extract_frames, video_path)
    if not frames:
        raise RuntimeError(
            f"[BluesmindFallbackError] No frames could be extracted from '{video_path}'"
        )

    try:
        content_parts = [{"type": "text", "text": _VISUAL_PROMPT}]
        for frame_path in frames:
            with open(frame_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })

        payload = {
            "model": "mimo-v2.5",
            "messages": [{"role": "user", "content": content_parts}],
            "max_tokens": 2048,
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
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError(
                f"[BluesmindFallbackError] API returned empty choices. Response: {data}"
            )
        visual_summary = choices[0].get("message", {}).get("content", "").strip()
        if not visual_summary:
            raise RuntimeError(
                f"[BluesmindFallbackError] API returned empty content. Response: {data}"
            )

        logger.info(f"[Visual] Bluesmind summary preview: {visual_summary[:200]}...")
        return visual_summary
    finally:
        for f in frames:
            _unlink_safe(f)


def _extract_frames(video_path: str) -> list[str]:
    import math

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
    try:
        os.unlink(path)
    except Exception:
        pass
