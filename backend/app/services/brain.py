"""
app/services/brain.py — Cognee knowledge graph integration + AI summary merging.

Responsibilities:
  - generate_unified_summary: Merge audio transcript + visual context into one
                              cohesive paragraph using Groq (Llama 3.3).
  - save_to_memory:           Persist the unified summary into the Cognee graph.
  - query_memory:             Search the graph with a natural language query.

Design constraints:
  - Groq, Neo4j, and Cognee clients are NEVER instantiated at the module level.
  - All imports of external clients are deferred (inside functions).
  - Callers receive typed exceptions (ConnectionError / RuntimeError) so
    routes.py can log the correct error category label.
"""

import os
import logging

logger = logging.getLogger("spillthereel.brain")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DATASET_NAME = "reel_knowledge"
_MERGE_MODEL = "llama-3.3-70b-versatile"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_unified_summary(audio_transcript: str, visual_context: str) -> str:
    """
    Merge an audio transcript and a visual context description into one
    cohesive paragraph using Groq (Llama 3.3 70B).

    The Groq client is instantiated INSIDE this function to avoid
    module-level initialisation crashes.

    Args:
        audio_transcript: Plain-text transcript from Groq Whisper.
        visual_context:   Visual description from Gemini 1.5 Flash.

    Returns:
        A single, cohesive summary paragraph covering both modalities.

    Raises:
        RuntimeError: If GROQ_API_KEY is missing or the API call fails.
    """
    from groq import Groq  # deferred import

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "[ConfigurationError] GROQ_API_KEY environment variable is not set. "
            "Add it to backend/.env."
        )

    groq_client = Groq(api_key=api_key)

    merge_prompt = f"""\
You are a multimodal content analyst. You have been given two descriptions of the same short-form video:

AUDIO TRANSCRIPT:
{audio_transcript}

VISUAL CONTEXT:
{visual_context}

Write a single cohesive paragraph (3–5 sentences) that integrates both the spoken content
and the visual elements into one unified summary. Be specific, factual, and concise.
Do not use bullet points or headings. Output only the paragraph, nothing else.
"""

    logger.info("[Brain] Generating unified multimodal summary with Groq Llama 3.3...")
    try:
        response = groq_client.chat.completions.create(
            model=_MERGE_MODEL,
            messages=[{"role": "user", "content": merge_prompt}],
            temperature=0.3,
            max_tokens=512,
        )
        unified_summary = response.choices[0].message.content.strip()
    except Exception as exc:
        raise RuntimeError(
            f"[SummaryMergeError] Groq failed to generate unified summary: {exc}"
        ) from exc

    logger.info(f"[Brain] Unified summary preview: {unified_summary[:200]}...")
    return unified_summary


async def save_to_memory(url: str, unified_summary: str) -> None:
    """
    Persist a reel's unified multimodal summary into the Cognee knowledge graph.

    The document stored in the graph combines the source URL with the AI-merged
    summary (audio + visual), giving Cognee rich, queryable context.

    The full pipeline:
      1. cognee.add     — ingest the document into the dataset.
      2. cognee.cognify — extract entities, relationships, and build vector index.

    Cognee is imported inside this function to avoid module-level init crashes.

    Args:
        url:            Source URL of the reel (provenance metadata).
        unified_summary: Cohesive paragraph from generate_unified_summary().

    Raises:
        ConnectionError: If Neo4j / LanceDB is unreachable.
        RuntimeError:    For any other Cognee-side failure.
    """
    import cognee  # deferred — avoids import-time Cognee initialisation

    document_text = (
        f"Source URL: {url}\n\n"
        f"Multimodal Summary:\n{unified_summary}"
    )

    logger.info(f"[Brain] [1/2] Adding document to dataset '{_DATASET_NAME}'...")
    try:
        await cognee.add(document_text, _DATASET_NAME)
    except Exception as exc:
        _raise_typed(exc, context=f"cognee.add for '{url}'")

    logger.info(f"[Brain] [2/2] Running cognify on dataset '{_DATASET_NAME}'...")
    try:
        await cognee.cognify(_DATASET_NAME)
    except Exception as exc:
        _raise_typed(exc, context=f"cognee.cognify for '{url}'")

    logger.info(f"[Brain] ✅ Knowledge graph updated for: {url}")


async def query_memory(question: str) -> object:
    """
    Search the Cognee knowledge graph with a natural language *question*.

    Uses HYBRID_COMPLETION search (graph + vector) for best recall.

    Cognee is imported inside this function to avoid module-level init crashes.

    Args:
        question: Natural language question from the user.

    Returns:
        One of:
        - A list of Cognee search result objects (normal case).
        - The string sentinel "__EMPTY_GRAPH__" if the DB is not yet
          initialized (no reels ingested yet). Callers must check for this.

    Raises:
        ConnectionError: If Neo4j is unreachable.
        RuntimeError:    For any other Cognee-side failure that is NOT
                         an uninitialized-DB error.
    """
    import cognee  # deferred import
    from cognee.modules.search.types.SearchType import SearchType  # deferred import

    logger.info(f"[Brain] Querying knowledge graph: '{question}'")
    try:
        results = await cognee.search(question, query_type=SearchType.HYBRID_COMPLETION)
    except Exception as exc:
        # ------------------------------------------------------------------
        # Detect empty / uninitialized graph errors:
        #   - sqlite3.OperationalError: unable to open database file
        #     (DB file doesn't exist yet — no reel has been ingested)
        #   - sqlite3.OperationalError: no such table: ...
        #     (DB exists but schema not yet created)
        # These are wrapped inside a chain of Cognee / SQLAlchemy exceptions.
        # Walk the full exception chain before deciding to re-raise.
        # ------------------------------------------------------------------
        exc_chain = str(exc).lower()
        cause = exc.__cause__
        while cause is not None:
            exc_chain += " " + str(cause).lower()
            cause = cause.__cause__

        empty_graph_signals = (
            "unable to open database file",
            "no such table",
            "operationalerror",
            "database is locked",
        )
        if any(sig in exc_chain for sig in empty_graph_signals):
            logger.warning(
                f"[Brain] Knowledge graph is empty or uninitialized. "
                f"Returning sentinel for '{question}'. Root cause: {exc}"
            )
            return "__EMPTY_GRAPH__"

        _raise_typed(exc, context=f"cognee.search for '{question}'")

    logger.info(f"[Brain] Query returned {len(results) if isinstance(results, list) else '?'} result(s).")
    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _raise_typed(exc: Exception, context: str) -> None:
    """
    Re-raise *exc* as a semantically meaningful exception type so that callers
    can log the correct error category label.

    Categories:
      - ConnectionError  → Neo4j / network connectivity issues.
      - RuntimeError     → All other Cognee / LanceDB failures.
    """
    msg = str(exc).lower()
    connection_keywords = (
        "connection refused",
        "failed to establish",
        "neo4j",
        "bolt",
        "timed out",
        "unreachable",
        "network",
        "serviceunavailable",
    )
    if any(kw in msg for kw in connection_keywords):
        raise ConnectionError(
            f"[DatabaseConnectionError] {context} — Neo4j unreachable: {exc}"
        ) from exc

    raise RuntimeError(
        f"[CogneeError] {context} — {type(exc).__name__}: {exc}"
    ) from exc
