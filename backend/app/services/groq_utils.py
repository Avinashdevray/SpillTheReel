import os
import logging
from groq import Groq

logger = logging.getLogger("spillthereel.groq_utils")

_RATE_LIMIT_TOKENS = ("429", "rate_limit", "too many requests", "503", "service unavailable")


def _is_rate_limit(exc: Exception) -> bool:
    err = str(exc).lower()
    return any(t in err for t in _RATE_LIMIT_TOKENS)


def get_keys() -> tuple[str | None, str | None]:
    return os.getenv("GROQ_API_KEY"), os.getenv("GROQ_API_KEY2")


def _ensure_key(api_key: str | None, api_key2: str | None) -> str:
    key = api_key or api_key2
    if not key:
        raise RuntimeError("[ConfigurationError] No GROQ_API_KEY or GROQ_API_KEY2 set.")
    return key


def call_groq(fn, *args, **kwargs):
    """Call a sync Groq function; retry with GROQ_API_KEY2 on rate limits."""
    from groq import Groq

    api_key, api_key2 = get_keys()
    key = _ensure_key(api_key, api_key2)

    try:
        return fn(Groq(api_key=key), *args, **kwargs)
    except Exception as exc:
        if api_key and api_key2 and _is_rate_limit(exc):
            logger.warning("[Groq] Rate limited on primary key. Retrying with GROQ_API_KEY2...")
            return fn(Groq(api_key=api_key2), *args, **kwargs)
        raise
