"""
app/services/brain.py — Cognee knowledge graph integration + AI summary merging.

All blocking I/O (Groq API calls) is offloaded to asyncio.to_thread.
Cognee Cloud is used when COGNEE_CLOUD_URL and COGNEE_CLOUD_API_KEY are set.
Otherwise falls back to local LanceDB (no search — Neo4j only).
"""

import asyncio
import logging
import os

logger = logging.getLogger("spillthereel.brain")

_DATASET_NAME = "reel_knowledge"
_MERGE_MODEL = "llama-3.3-70b-versatile"
_CHAT_SEARCH_TIMEOUT = 30


def _use_cloud() -> bool:
    return bool(os.getenv("COGNEE_CLOUD_URL") and os.getenv("COGNEE_CLOUD_API_KEY"))


async def generate_unified_summary(audio_transcript: str, visual_context: str) -> str:
    from app.services.groq_utils import call_groq

    merge_prompt = f"""\
You are a multimodal content analyst. You have been given two descriptions of the same short-form video:

AUDIO TRANSCRIPT:
{audio_transcript}

VISUAL CONTEXT:
{visual_context}

Write a single cohesive paragraph (3-5 sentences) that integrates both the spoken content
and the visual elements into one unified summary. Be specific, factual, and concise.
Do not use bullet points or headings. Output only the paragraph, nothing else.
"""

    logger.info("[Brain] Generating unified multimodal summary with Groq Llama 3.3...")
    try:
        response = await asyncio.to_thread(
            call_groq,
            lambda c: c.chat.completions.create(
                model=_MERGE_MODEL,
                messages=[{"role": "user", "content": merge_prompt}],
                temperature=0.3,
                max_tokens=512,
            ),
        )
        unified_summary = response.choices[0].message.content.strip()
    except Exception as exc:
        raise RuntimeError(
            f"[SummaryMergeError] Groq failed to generate unified summary: {exc}"
        ) from exc

    logger.info(f"[Brain] Unified summary preview: {unified_summary[:200]}...")
    return unified_summary


async def generate_chat_answer(question: str, reel: dict) -> str:
    from app.services.groq_utils import call_groq

    system_msg = """\
You are a helpful AI assistant answering questions about a user's saved Instagram Reels.
Rules:
- Never use markdown formatting: no asterisks (*), no double asterisks (**), no hash symbols (#), no backticks (`), no brackets.
- Write in plain text only. Use words like "bold" or "emphasized" if you need to highlight something.
- Answer directly using only the transcript and summary provided below.
- Include the author's name in your response.
- Be concise and helpful."""

    user_prompt = f"""\
Question: "{question}"

Here is the transcript and summary of the most relevant reel:
Author: {reel.get('author', 'Unknown')}
Summary:
{reel.get('summary', '')}

Transcript:
{reel.get('transcript', '')}

Answer the user's question using only the information above."""
    try:
        response = await asyncio.to_thread(
            call_groq,
            lambda c: c.chat.completions.create(
                model=_MERGE_MODEL,
                messages=[{"role": "system", "content": system_msg},
                          {"role": "user", "content": user_prompt}],
                temperature=0.3,
                max_tokens=512,
            ),
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.error(f"[ChatAnswerError] {exc}")
        return "I found this reel that matches your query!"


async def save_to_memory(url: str, unified_summary: str, uid: str = "") -> None:
    import cognee

    dataset = f"{_DATASET_NAME}_{uid}" if uid else _DATASET_NAME

    document_text = (
        f"Source URL: {url}\n\n"
        f"Multimodal Summary:\n{unified_summary}"
    )

    _COGNEE_TIMEOUT = 60

    if _use_cloud():
        logger.info(f"[Brain] Saving to Cognee Cloud dataset '{dataset}'...")
        try:
            await asyncio.wait_for(
                cognee.remember(document_text, dataset_name=dataset),
                timeout=_COGNEE_TIMEOUT,
            )
            logger.info(f"[Brain] Cognee Cloud remember complete for: {url}")
        except Exception as exc:
            logger.warning(f"[Brain] Cognee Cloud save warning (non-fatal): {exc}")
    else:
        logger.info(f"[Brain] Adding document to local dataset '{dataset}'...")
        try:
            await asyncio.wait_for(cognee.add(document_text, dataset), timeout=_COGNEE_TIMEOUT)
        except asyncio.TimeoutError:
            raise RuntimeError(f"[CogneeTimeout] cognee.add timed out after {_COGNEE_TIMEOUT}s for '{url}'")
        except Exception as exc:
            _raise_typed(exc, context=f"cognee.add for '{url}'")

        logger.info(f"[Brain] Entity extraction (cognify) skipped — no Cognee Cloud.")
        logger.info(f"[Brain] Data stored in LanceDB + Neo4j for: {url}")


async def query_memory(question: str, uid: str = ""):
    import cognee

    if not _use_cloud():
        logger.info("[Brain] Cognee Cloud not configured — skipping vector search.")
        return "__EMPTY_GRAPH__"

    dataset = f"{_DATASET_NAME}_{uid}" if uid else _DATASET_NAME
    logger.info(f"[Brain] Querying Cognee Cloud dataset '{dataset}': '{question}'")
    try:
        results = await asyncio.wait_for(
            cognee.recall(query_text=question, datasets=[dataset]),
            timeout=_CHAT_SEARCH_TIMEOUT,
        )
        logger.info(f"[Brain] Cognee Cloud returned {len(results) if isinstance(results, list) else '?'} result(s).")
        return results
    except asyncio.TimeoutError:
        logger.warning(f"[Brain] Cognee Cloud search timed out for '{question}'")
        return "__EMPTY_GRAPH__"
    except Exception as exc:
        logger.warning(f"[Brain] Cognee Cloud search failed: {exc}")
        return "__EMPTY_GRAPH__"


def _raise_typed(exc: Exception, context: str) -> None:
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
