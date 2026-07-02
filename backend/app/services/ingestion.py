"""
app/services/ingestion.py — Video download and audio transcription service.

Cookie strategy (NON-NEGOTIABLE):
  - ALWAYS uses 'cookiefile': 'cookies.txt' (resolved relative to backend/).
  - If cookies.txt does not exist, raises FileNotFoundError immediately.
  - NEVER falls back to cookiesfrombrowser or any browser-based extraction.

Public API (two separate, composable steps):
  1. download_video(url)       → (video_path: str, tmpdir: TemporaryDirectory)
     Downloads the best-quality MP4 into a managed temp directory.
     The caller MUST call tmpdir.cleanup() when done (after Gemini upload).

  2. transcribe_audio(video_path) → str
     Sends the local video/audio file to Groq Whisper and returns the transcript.

Why separate?
  The Gemini Files API requires the local file to remain on disk during upload
  and polling. Merging download + transcription into one function (and using a
  `with tempfile.TemporaryDirectory()` context manager) would delete the file
  before Gemini can read it. The caller in routes.py manages cleanup explicitly.
"""

import os
import logging
import tempfile
from pathlib import Path

import yt_dlp

logger = logging.getLogger("spillthereel.ingestion")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# cookies.txt must live in the backend/ directory (two levels above this file)
_COOKIES_FILE = Path(__file__).resolve().parents[2] / "cookies.txt"

# Download the full video (video + audio merged) so Gemini can extract visuals.
# 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best' gives us a proper
# MP4 without needing ffmpeg for remux in most cases.
_YDL_FORMAT = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
_VIDEO_FILENAME = "video.%(ext)s"
_WHISPER_MODEL = "whisper-large-v3"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def download_video(url: str) -> tuple[str, tempfile.TemporaryDirectory]:
    """
    Download the best-quality video from *url* into a temporary directory.

    Cookie strategy:
      - Reads authentication cookies from cookies.txt (Netscape format).
      - Raises FileNotFoundError if cookies.txt is absent.
      - Does NOT use cookiesfrombrowser under any circumstances.

    IMPORTANT — temp dir lifetime:
      The caller receives the TemporaryDirectory object and MUST call
      ``tmpdir.cleanup()`` after they no longer need the video file.
      Forgetting to do so leaks disk space.

    Args:
        url: The reel / video URL to download.

    Returns:
        (video_path, tmpdir) — absolute path to the downloaded file and the
        TemporaryDirectory managing it.

    Raises:
        FileNotFoundError: If cookies.txt does not exist.
        ConnectionError:   If yt-dlp reports a network-level failure.
        RuntimeError:      If yt-dlp exits with any other error.
    """
    # ------------------------------------------------------------------
    # Guard: cookies.txt MUST exist before we attempt any network call
    # ------------------------------------------------------------------
    if not _COOKIES_FILE.exists():
        raise FileNotFoundError(
            f"[AuthenticationError] cookies.txt not found at '{_COOKIES_FILE}'. "
            "Export your browser cookies in Netscape format and place the file there. "
            "See: https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp"
        )

    logger.info(f"[Ingestion] cookies.txt located at: {_COOKIES_FILE}")
    logger.info(f"[Ingestion] Downloading video from: {url}")

    # Use explicit object (not `with` statement) so tmpdir outlives this function
    tmpdir = tempfile.TemporaryDirectory()
    video_template = os.path.join(tmpdir.name, _VIDEO_FILENAME)

    ydl_opts = {
        "format": _YDL_FORMAT,
        "outtmpl": video_template,
        "quiet": True,
        "no_warnings": False,
        "merge_output_format": "mp4",   # Force MP4 container when merging streams
        # -------------------------------------------------------
        # Cookie strategy — cookiefile ONLY. No browser fallback.
        # -------------------------------------------------------
        "cookiefile": str(_COOKIES_FILE),
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # Resolve the actual filename (extension is format-dependent)
            downloaded_path = ydl.prepare_filename(info)
            # yt-dlp may write .mp4 after merging — resolve the real path
            downloaded_path = _resolve_actual_path(downloaded_path, tmpdir.name)
    except yt_dlp.utils.DownloadError as exc:
        tmpdir.cleanup()  # Don't leak temp dir on failure
        msg = str(exc).lower()
        if any(term in msg for term in ("network", "connection", "timed out", "unable to connect")):
            raise ConnectionError(
                f"[NetworkError] yt-dlp network failure for '{url}': {exc}"
            ) from exc
        raise RuntimeError(
            f"[DownloadError] yt-dlp failed for '{url}': {exc}"
        ) from exc
    except Exception as exc:
        tmpdir.cleanup()
        raise RuntimeError(
            f"[DownloadError] Unexpected error downloading '{url}': {exc}"
        ) from exc

    logger.info(f"[Ingestion] ✅ Download complete → {downloaded_path}")
    return downloaded_path, tmpdir


async def transcribe_audio(video_path: str) -> str:
    """
    Transcribe the audio track of *video_path* using Groq Whisper.

    Works with any audio/video file format that Groq Whisper accepts
    (MP4, MP3, WAV, WEBM, etc.).

    The Groq client is instantiated INSIDE this function to prevent
    module-level initialisation crashes if GROQ_API_KEY is not yet loaded.

    Args:
        video_path: Absolute path to the downloaded video/audio file.

    Returns:
        The transcript as a plain string.

    Raises:
        RuntimeError: If GROQ_API_KEY is missing or the API call fails.
    """
    from groq import Groq  # deferred import — client created inside function

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "[ConfigurationError] GROQ_API_KEY environment variable is not set. "
            "Add it to backend/.env."
        )

    groq_client = Groq(api_key=api_key)

    logger.info(f"[Ingestion] Transcribing audio via Groq Whisper: {os.path.basename(video_path)}")
    try:
        with open(video_path, "rb") as audio_file:
            response = groq_client.audio.transcriptions.create(
                file=(os.path.basename(video_path), audio_file.read()),
                model=_WHISPER_MODEL,
                response_format="text",
            )
    except Exception as exc:
        raise RuntimeError(
            f"[TranscriptionError] Groq Whisper API failed for '{video_path}': {exc}"
        ) from exc

    # Groq returns plain string when response_format="text"
    transcript = str(response)
    logger.info(f"[Ingestion] Transcript preview: {transcript[:200]}...")
    return transcript


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_actual_path(prepared_path: str, tmpdir: str) -> str:
    """
    yt-dlp's prepare_filename() returns the *intended* path, but after format
    merging the actual file may have a different extension (always .mp4 here).
    Scan the temp directory for the largest file as a fallback.
    """
    if os.path.exists(prepared_path):
        return prepared_path

    # Check for .mp4 variant of the same stem
    stem = Path(prepared_path).stem
    mp4_path = os.path.join(tmpdir, f"{stem}.mp4")
    if os.path.exists(mp4_path):
        return mp4_path

    # Last resort: return the biggest file in the temp directory
    files = [
        os.path.join(tmpdir, f) for f in os.listdir(tmpdir)
        if os.path.isfile(os.path.join(tmpdir, f))
    ]
    if files:
        return max(files, key=os.path.getsize)

    raise RuntimeError(
        f"[DownloadError] No video file found in temp directory '{tmpdir}' "
        f"after yt-dlp reported success. Expected path: '{prepared_path}'."
    )
