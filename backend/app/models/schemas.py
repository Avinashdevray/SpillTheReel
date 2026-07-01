"""
SpillTheReel – Pydantic Schemas

Strict type definitions for API request/response payloads.
"""

from pydantic import BaseModel, Field, HttpUrl
from datetime import datetime


class ReelIngestRequest(BaseModel):
    """Incoming request to ingest a video URL."""

    url: HttpUrl = Field(..., description="Public URL of the reel / short / video to ingest.")
    tags: list[str] = Field(
        default_factory=list,
        description="Optional user-supplied tags for categorisation.",
    )


class SceneSegment(BaseModel):
    """A single detected scene within the video."""

    start_time: float = Field(..., description="Scene start in seconds.")
    end_time: float = Field(..., description="Scene end in seconds.")
    description: str = Field(default="", description="Visual caption for the scene (Moondream).")


class UnifiedVideoPayload(BaseModel):
    """
    Unified representation of a fully processed video.
    Returned by the ingestion pipeline and stored in Cognee.
    """

    source_url: str = Field(..., description="Original video URL.")
    title: str = Field(default="Untitled", description="Video title extracted by yt-dlp.")
    transcript: str = Field(default="", description="Full transcript from faster-whisper.")
    ocr_texts: list[str] = Field(
        default_factory=list,
        description="On-screen text segments extracted via EasyOCR.",
    )
    scenes: list[SceneSegment] = Field(
        default_factory=list,
        description="Scene-level breakdowns with visual captions.",
    )
    tags: list[str] = Field(default_factory=list, description="User or auto-generated tags.")
    ingested_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp of ingestion.",
    )


class SearchQuery(BaseModel):
    """Incoming search request."""

    query: str = Field(..., min_length=1, description="Natural-language search query.")
    top_k: int = Field(default=5, ge=1, le=50, description="Number of results to return.")


class SearchResult(BaseModel):
    """A single search result from the knowledge graph."""

    source_url: str = Field(..., description="Original video URL.")
    title: str = Field(default="Untitled", description="Video title.")
    snippet: str = Field(default="", description="Relevant text snippet.")
    score: float = Field(default=0.0, ge=0.0, le=1.0, description="Relevance score.")
