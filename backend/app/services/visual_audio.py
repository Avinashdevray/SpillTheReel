"""
SpillTheReel – Visual & Audio Processing Service

Handles:
  - Audio transcription via faster-whisper (WhisperX-compatible)
  - Scene detection via PySceneDetect
  - On-screen text extraction via EasyOCR
  - Visual captioning via Moondream (placeholder – model integration pending)
"""

import logging
from pathlib import Path

from app.models.schemas import UnifiedVideoPayload, SceneSegment

logger = logging.getLogger(__name__)


async def _transcribe_audio(file_path: str) -> str:
    """
    Transcribe audio from a video file using faster-whisper.

    Returns the full transcript as a single string.
    """
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel("base", compute_type="int8")
        segments, _info = model.transcribe(file_path, beam_size=5)
        transcript = " ".join(segment.text.strip() for segment in segments)
        logger.info("Transcription complete (%d chars).", len(transcript))
        return transcript
    except ImportError:
        logger.warning("faster-whisper not available; returning empty transcript.")
        return "[transcript unavailable – faster-whisper not installed]"
    except Exception as exc:
        logger.exception("Transcription failed: %s", exc)
        return "[transcript error]"


async def _detect_scenes(file_path: str) -> list[SceneSegment]:
    """
    Detect scene boundaries using PySceneDetect.

    Returns a list of SceneSegment objects.
    """
    try:
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import ContentDetector

        video = open_video(file_path)
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=30.0))
        scene_manager.detect_scenes(video)

        scene_list = scene_manager.get_scene_list()
        segments = [
            SceneSegment(
                start_time=start.get_seconds(),
                end_time=end.get_seconds(),
                description="",  # Captioning applied separately
            )
            for start, end in scene_list
        ]
        logger.info("Detected %d scenes.", len(segments))
        return segments
    except ImportError:
        logger.warning("scenedetect not available; returning empty scene list.")
        return []
    except Exception as exc:
        logger.exception("Scene detection failed: %s", exc)
        return []


async def _extract_ocr_text(file_path: str) -> list[str]:
    """
    Extract on-screen text from video key-frames using EasyOCR.

    Returns a list of unique text strings found.
    """
    try:
        import easyocr
        import cv2

        reader = easyocr.Reader(["en"], gpu=False)
        cap = cv2.VideoCapture(file_path)

        texts: list[str] = []
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        sample_interval = max(frame_count // 10, 1)  # Sample ~10 frames

        idx = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            if idx % sample_interval == 0:
                results = reader.readtext(frame, detail=0)
                texts.extend(results)
            idx += 1

        cap.release()
        unique_texts = list(dict.fromkeys(texts))  # Deduplicate, preserve order
        logger.info("OCR extracted %d unique text segments.", len(unique_texts))
        return unique_texts
    except ImportError:
        logger.warning("easyocr / cv2 not available; returning empty OCR list.")
        return []
    except Exception as exc:
        logger.exception("OCR extraction failed: %s", exc)
        return []


async def process_video(
    file_path: str,
    source_url: str,
    tags: list[str] | None = None,
) -> UnifiedVideoPayload:
    """
    Run the full visual-audio processing pipeline on a downloaded video.

    Orchestrates transcription, scene detection, and OCR, then assembles
    a UnifiedVideoPayload.
    """
    video_title = Path(file_path).stem

    transcript = await _transcribe_audio(file_path)
    scenes = await _detect_scenes(file_path)
    ocr_texts = await _extract_ocr_text(file_path)

    payload = UnifiedVideoPayload(
        source_url=source_url,
        title=video_title,
        transcript=transcript,
        ocr_texts=ocr_texts,
        scenes=scenes,
        tags=tags or [],
    )

    logger.info("Video processing complete for '%s'.", video_title)
    return payload
