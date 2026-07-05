"""
app/services/ingestion.py — Video download and audio transcription service.

All blocking I/O (yt-dlp, ffmpeg, Groq API) is offloaded to a thread pool
via asyncio.to_thread to avoid freezing the event loop.
"""

import os
import asyncio
import subprocess
import logging
import tempfile
from pathlib import Path

import yt_dlp

logger = logging.getLogger("spillthereel.ingestion")

_COOKIES_FILE = Path(__file__).resolve().parents[2] / "cookies.txt"
_YDL_FORMAT = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
_VIDEO_FILENAME = "video.%(ext)s"
_WHISPER_MODEL = "whisper-large-v3"


async def download_video(url: str) -> tuple[str, tempfile.TemporaryDirectory, dict]:
    logger.info(f"[Ingestion] Downloading video from: {url}")

    tmpdir = tempfile.TemporaryDirectory()
    video_template = os.path.join(tmpdir.name, _VIDEO_FILENAME)

    ydl_opts = {
        "format": _YDL_FORMAT,
        "outtmpl": video_template,
        "quiet": True,
        "no_warnings": False,
        "merge_output_format": "mp4",
    }

    if _COOKIES_FILE.exists():
        logger.info(f"[Ingestion] cookies.txt located at: {_COOKIES_FILE}")
        ydl_opts["cookiefile"] = str(_COOKIES_FILE)
    else:
        logger.warning(f"[Ingestion] cookies.txt not found at {_COOKIES_FILE}. Proceeding without cookies.")

    def _do_download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            metadata = {
                "author": info.get("uploader") or info.get("channel") or "Unknown",
                "thumbnail": info.get("thumbnail") or ""
            }
            downloaded_path = ydl.prepare_filename(info)
            downloaded_path = _resolve_actual_path(downloaded_path, tmpdir.name)
            return downloaded_path, metadata

    try:
        downloaded_path, metadata = await asyncio.to_thread(_do_download)
    except yt_dlp.utils.DownloadError as exc:
        tmpdir.cleanup()
        msg = str(exc).lower()
        if any(term in msg for term in ("network", "connection", "timed out", "unable to connect")):
            raise ConnectionError(f"[NetworkError] yt-dlp network failure for '{url}': {exc}") from exc
        raise RuntimeError(f"[DownloadError] yt-dlp failed for '{url}': {exc}") from exc
    except Exception as exc:
        tmpdir.cleanup()
        raise RuntimeError(f"[DownloadError] Unexpected error downloading '{url}': {exc}") from exc

    logger.info(f"[Ingestion] Download complete -> {downloaded_path}")
    return downloaded_path, tmpdir, metadata


async def transcribe_audio(video_path: str) -> str:
    from app.services.groq_utils import call_groq

    audio_path = await asyncio.to_thread(_extract_audio, video_path)

    logger.info(f"[Ingestion] Transcribing audio via Groq Whisper: {os.path.basename(audio_path)}")

    def _do_transcribe(client):
        with open(audio_path, "rb") as audio_file:
            return client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), audio_file.read()),
                model=_WHISPER_MODEL,
                response_format="text",
            )

    try:
        response = await asyncio.to_thread(call_groq, _do_transcribe)
    except Exception as exc:
        raise RuntimeError(
            f"[TranscriptionError] Groq Whisper API failed for '{video_path}': {exc}"
        ) from exc
    finally:
        _safe_unlink(audio_path)

    transcript = str(response)
    logger.info(f"[Ingestion] Transcript preview: {transcript[:200]}...")
    return transcript


def _extract_audio(video_path: str) -> str:
    audio_path = Path(video_path).with_suffix(".mp3")

    logger.info(
        f"[Ingestion] Extracting audio via ffmpeg: {os.path.basename(video_path)} "
        f"-> {audio_path.name}"
    )
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", video_path,
                "-vn",
                "-acodec", "libmp3lame",
                "-ab", "128k",
                "-ar", "44100",
                "-ac", "1",
                str(audio_path),
            ],
            capture_output=True,
            check=True,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "[ConfigurationError] ffmpeg is not installed. "
            "Install it via 'brew install ffmpeg' (macOS) or 'apt install ffmpeg' (Linux)."
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
        raise RuntimeError(
            f"[AudioExtractionError] ffmpeg failed for '{video_path}': {stderr[:500]}"
        ) from exc

    logger.info(f"[Ingestion] Audio extracted -> {audio_path} ({audio_path.stat().st_size // 1024} KB)")
    return str(audio_path)


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except Exception:
        pass


def _resolve_actual_path(prepared_path: str, tmpdir: str) -> str:
    if os.path.exists(prepared_path):
        return prepared_path

    stem = Path(prepared_path).stem
    for ext in [".mp4", ".mkv", ".webm"]:
        candidate = os.path.join(tmpdir, f"{stem}{ext}")
        if os.path.exists(candidate):
            return candidate

    files = [
        os.path.join(tmpdir, f) for f in os.listdir(tmpdir)
        if os.path.isfile(os.path.join(tmpdir, f)) and not f.endswith(".part")
    ]
    mp4_files = [f for f in files if f.endswith(".mp4")]
    if mp4_files:
        return max(mp4_files, key=os.path.getsize)
    if files:
        return max(files, key=os.path.getsize)

    raise RuntimeError(
        f"[DownloadError] No video file found in temp directory '{tmpdir}' "
        f"after yt-dlp reported success."
    )
