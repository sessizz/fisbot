import base64
import logging

import httpx

from fisbot.config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT
from fisbot.prompt import RECEIPT_EXTRACTION_PROMPT, MULTI_RECEIPT_HINT

logger = logging.getLogger(__name__)


async def check_ollama() -> bool:
    """Check if Ollama is running and the configured model is available."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=10)
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            model_base = OLLAMA_MODEL.split(":")[0]
            found = any(model_base in m for m in models)
            if not found:
                logger.error(
                    "Model '%s' not found. Available: %s. "
                    "Run: ollama pull %s",
                    OLLAMA_MODEL, models, OLLAMA_MODEL,
                )
            return found
    except httpx.ConnectError:
        logger.error(
            "Cannot connect to Ollama at %s. Is it running? Try: ollama serve",
            OLLAMA_BASE_URL,
        )
        return False


async def extract_receipt(image_bytes: bytes, multi: bool = False) -> str:
    """Send an image to Ollama vision model and return the raw text response."""
    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    prompt = RECEIPT_EXTRACTION_PROMPT
    if multi:
        prompt += MULTI_RECEIPT_HINT

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [b64_image],
            }
        ],
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 4096,
        },
    }

    async with httpx.AsyncClient() as client:
        logger.info("Sending image to Ollama (%s)...", OLLAMA_MODEL)
        resp = await client.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

    content = data.get("message", {}).get("content", "")
    logger.info("Ollama response length: %d chars", len(content))
    return content
