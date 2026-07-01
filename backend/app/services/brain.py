"""
SpillTheReel – Brain Service (Cognee Memory Layer)

Manages storage and retrieval of UnifiedVideoPayload objects
in the Cognee knowledge graph.
"""

import logging

from app.models.schemas import UnifiedVideoPayload, SearchResult

logger = logging.getLogger(__name__)


async def store_in_memory(payload: UnifiedVideoPayload) -> bool:
    """
    Store a processed video payload in the Cognee knowledge graph.

    Args:
        payload: The unified video payload to persist.

    Returns:
        True if storage succeeded, False otherwise.
    """
    try:
        import cognee

        # Build a text document from the payload for Cognee ingestion
        document_text = _build_document_text(payload)

        await cognee.add(document_text, dataset_name="spillthereel_videos")
        await cognee.cognify()

        logger.info("Stored payload in Cognee for: %s", payload.source_url)
        return True
    except ImportError:
        logger.warning(
            "cognee is not installed. Payload for '%s' was NOT stored. "
            "Run: pip install cognee",
            payload.source_url,
        )
        return False
    except Exception as exc:
        logger.exception("Failed to store payload in Cognee: %s", exc)
        return False


async def query_memory(query: str, top_k: int = 5) -> list[SearchResult]:
    """
    Perform a semantic search across the Cognee knowledge graph.

    Args:
        query: Natural-language search string.
        top_k: Maximum number of results to return.

    Returns:
        A list of SearchResult objects ranked by relevance.
    """
    try:
        import cognee

        raw_results = await cognee.search("SIMILARITY", query=query)

        results: list[SearchResult] = []
        for item in raw_results[:top_k]:
            # Cognee returns varied shapes; normalise defensively
            text = str(item) if not isinstance(item, dict) else item.get("text", str(item))
            results.append(
                SearchResult(
                    source_url="",  # Graph enrichment will link back to source
                    title="Knowledge Graph Result",
                    snippet=text[:500],
                    score=0.0,
                )
            )

        logger.info("Search returned %d results for query: '%s'", len(results), query)
        return results
    except ImportError:
        logger.warning("cognee is not installed. Returning empty search results.")
        return []
    except Exception as exc:
        logger.exception("Cognee search failed: %s", exc)
        return []


def _build_document_text(payload: UnifiedVideoPayload) -> str:
    """Flatten a UnifiedVideoPayload into a single text document for Cognee."""
    parts: list[str] = [
        f"Title: {payload.title}",
        f"Source: {payload.source_url}",
        f"Tags: {', '.join(payload.tags) if payload.tags else 'none'}",
        "",
        "## Transcript",
        payload.transcript or "(no transcript)",
        "",
    ]

    if payload.ocr_texts:
        parts.append("## On-Screen Text (OCR)")
        parts.extend(f"- {t}" for t in payload.ocr_texts)
        parts.append("")

    if payload.scenes:
        parts.append("## Scenes")
        for i, scene in enumerate(payload.scenes, 1):
            parts.append(
                f"{i}. [{scene.start_time:.1f}s – {scene.end_time:.1f}s] "
                f"{scene.description or '(no caption)'}"
            )
        parts.append("")

    return "\n".join(parts)
