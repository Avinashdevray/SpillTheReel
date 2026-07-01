"""
SpillTheReel – Ingestion Service (yt-dlp layer)

Downloads video content from a given URL using yt-dlp.
"""

import os
import logging
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = Path(settings.download_dir)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


async def download_video(url: str) -> str | None:
    """
    Download a video from the given URL using yt-dlp.

    Args:
        url: Public video URL (YouTube, Instagram, TikTok, etc.)

    Returns:
        Absolute path to the downloaded file, or None on failure.
    """
    try:
        import yt_dlp

        output_template = str(DOWNLOAD_DIR / "%(title)s.%(ext)s")

        ydl_opts: dict = {
            "outtmpl": output_template,
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(str(url), download=True)
            if info is None:
                logger.error("yt-dlp returned no info for URL: %s", url)
                return None

            filename = ydl.prepare_filename(info)
            # Handle merged output extension
            base, _ = os.path.splitext(filename)
            final_path = f"{base}.mp4"

            if os.path.exists(final_path):
                logger.info("Downloaded: %s", final_path)
                return final_path

            # Fallback: return whatever file was written
            if os.path.exists(filename):
                return filename

            logger.warning("Download completed but file not found: %s", final_path)
            return None

    except ImportError:
        logger.error("yt-dlp is not installed. Run: pip install yt-dlp")
        return None
    except Exception as exc:
        logger.exception("Failed to download video from %s: %s", url, exc)
        return None
