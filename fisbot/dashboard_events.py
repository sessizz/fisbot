import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()


async def publish_event(event: dict[str, Any]) -> None:
    """Publish a dashboard event to all connected browser clients."""
    stale: list[asyncio.Queue[dict[str, Any]]] = []
    for queue in _subscribers:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            stale.append(queue)

    for queue in stale:
        _subscribers.discard(queue)


@asynccontextmanager
async def subscribe() -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
    _subscribers.add(queue)
    try:
        yield queue
    finally:
        _subscribers.discard(queue)
