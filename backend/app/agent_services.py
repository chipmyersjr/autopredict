"""Local inference and keyless research boundaries, without application retries."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.settings import Settings


class ResearchFailure(Exception):
    """Safe public classification; never include provider response details."""


@asynccontextmanager
async def local_model_client(settings: Settings, *, transport=None):
    from ollama import AsyncClient

    # Override SDK environment-key injection, disable proxy/netrc discovery and
    # HTTP transport retries. No model pull or hosted fallback is performed.
    client = AsyncClient(
        host=settings.ollama_host,
        headers={"Authorization": ""},
        timeout=httpx.Timeout(180, connect=10),
        trust_env=False,
        follow_redirects=False,
        transport=transport or httpx.AsyncHTTPTransport(retries=0),
    )
    # Some SDK releases populate Authorization from OLLAMA_API_KEY even when
    # headers were supplied. This dedicated client's requests never use it.
    client._client.headers.pop("authorization", None)
    try:
        yield client
    finally:
        await client._client.aclose()


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


def normalize_results(rows) -> list[SearchResult]:
    results = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title, url, body = (row.get(key) for key in ("title", "href", "body"))
        if not all(isinstance(value, str) and value.strip() for value in (title, url, body)):
            continue
        url = url.strip()
        try:
            parsed = urlsplit(url)
            valid = parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password
        except ValueError:
            valid = False
        if not valid or len(url) > 2048:
            continue
        results.append(SearchResult(title.strip()[:200], url, body.strip()[:1000]))
        if len(results) == 5:
            break
    if not results:
        raise ResearchFailure("Research unavailable")
    return results


class DuckDuckGoSearch:
    """One bounded synchronous search at a time per worker adapter.

    Cancellation discards the result but retains the slot until the finite
    transport call actually finishes. It cannot launch replacement threads.
    """

    def __init__(self, *, factory=None):
        self._factory = factory
        self._slot = asyncio.Semaphore(1)
        self._pending = set()

    def _search(self, query):
        factory = self._factory
        if factory is None:
            from ddgs import DDGS
            factory = DDGS
        # Explicit backend prohibits the library's multi-provider fallback.
        client = factory(timeout=10)
        try:
            return normalize_results(client.text(query, backend="duckduckgo", max_results=5))
        finally:
            close = getattr(client, "close", None)
            if close is not None:
                close()

    async def web_search(self, query: str) -> list[SearchResult]:
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise ResearchFailure("Invalid research query")
        await self._slot.acquire()
        task = asyncio.create_task(asyncio.to_thread(self._search, query.strip()))
        self._pending.add(task)

        def finished(done):
            self._pending.discard(done)
            self._slot.release()
            if not done.cancelled():
                done.exception()  # Retrieve errors even after caller cancellation.

        task.add_done_callback(finished)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ResearchFailure("Research unavailable") from None

    async def aclose(self):
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)
