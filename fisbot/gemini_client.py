import asyncio
import base64
import logging
import re
import time
from collections import deque

import google.api_core.exceptions
import google.generativeai as genai

from fisbot.config import GEMINI_API_KEY, GEMINI_MODELS
from fisbot.prompt import RECEIPT_EXTRACTION_PROMPT, MULTI_RECEIPT_HINT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiter: max 15 requests per 60-second rolling window
# ---------------------------------------------------------------------------
_RATE_LIMIT = 15
_RATE_WINDOW = 60  # seconds

_request_timestamps: deque[float] = deque()
_queue_lock = asyncio.Lock()


def _prune_old_timestamps() -> None:
    cutoff = time.monotonic() - _RATE_WINDOW
    while _request_timestamps and _request_timestamps[0] < cutoff:
        _request_timestamps.popleft()


def queue_position_info() -> tuple[int, float]:
    _prune_old_timestamps()
    available = _RATE_LIMIT - len(_request_timestamps)
    if available > 0:
        return available, 0.0
    wait = _request_timestamps[0] + _RATE_WINDOW - time.monotonic()
    return 0, max(wait, 0.0)


async def _wait_for_slot() -> float:
    total_wait = 0.0
    while True:
        _prune_old_timestamps()
        if len(_request_timestamps) < _RATE_LIMIT:
            _request_timestamps.append(time.monotonic())
            return total_wait
        wait = _request_timestamps[0] + _RATE_WINDOW - time.monotonic()
        wait = max(wait, 0.1)
        total_wait += wait
        await asyncio.sleep(wait)


# ---------------------------------------------------------------------------
# Gemini client with model fallback
# ---------------------------------------------------------------------------

_configured = False
_models: dict[str, genai.GenerativeModel] = {}


def _ensure_configured():
    global _configured
    if not _configured:
        genai.configure(api_key=GEMINI_API_KEY)
        _configured = True


def _get_model(model_name: str) -> genai.GenerativeModel:
    _ensure_configured()
    if model_name not in _models:
        _models[model_name] = genai.GenerativeModel(model_name)
    return _models[model_name]


async def check_gemini() -> bool:
    if not GEMINI_API_KEY:
        logger.error(
            "GEMINI_API_KEY is not set. "
            "Get a free key at https://aistudio.google.com/apikey "
            "and add it to your .env file."
        )
        return False
    try:
        model = _get_model(GEMINI_MODELS[0])
        await asyncio.to_thread(model.count_tokens, "test")
        logger.info("Gemini API connection OK (models: %s)", ", ".join(GEMINI_MODELS))
        return True
    except Exception as e:
        logger.error("Gemini API check failed: %s", e)
        return False


def _parse_retry_delay(error_msg: str) -> float:
    if "retry in" in error_msg.lower():
        m = re.search(r"retry in (\d+(?:\.\d+)?)", error_msg.lower())
        if m:
            return float(m.group(1)) + 1
    return 60.0


async def extract_receipt(
    image_bytes: bytes,
    multi: bool = False,
    on_queue: callable = None,
) -> str:
    prompt = RECEIPT_EXTRACTION_PROMPT
    if multi:
        prompt += MULTI_RECEIPT_HINT

    # Rate limiting
    async with _queue_lock:
        slots, wait = queue_position_info()
        if slots == 0 and on_queue:
            await on_queue(wait)
        waited = await _wait_for_slot()

    if waited > 0:
        logger.info("Rate-limit wait: %.1f seconds", waited)

    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    image_part = {"mime_type": "image/jpeg", "data": b64_image}

    # Try each model in order; fall back on quota/availability errors
    last_error = None
    for model_name in GEMINI_MODELS:
        model = _get_model(model_name)
        logger.info("Trying model: %s", model_name)

        try:
            response = await asyncio.to_thread(
                model.generate_content,
                [prompt, image_part],
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=16384,
                ),
            )
            content = response.text
            logger.info("Gemini [%s] response length: %d chars", model_name, len(content))
            logger.info("Gemini raw response:\n%s", content)
            return content
        except google.api_core.exceptions.ResourceExhausted as e:
            last_error = e
            logger.warning("%s quota exhausted, trying next model...", model_name)
        except google.api_core.exceptions.NotFound:
            logger.warning("Model %s not available, trying next...", model_name)
        except google.api_core.exceptions.InvalidArgument as e:
            last_error = e
            logger.warning("Model %s rejected request: %s, trying next...", model_name, e)

    raise last_error or RuntimeError("All Gemini models failed")
