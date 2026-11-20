import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app.agent_profiles import load_profile
from app.agent_services import DuckDuckGoSearch, ResearchFailure, local_model_client
from app.settings import Settings


def test_profiles_are_server_owned():
    assert "quarterback" in load_profile("FootballAnalysisExpert")
    for name in ("../settings.py", "/etc/passwd", "FootballAnalysisExpert.md", "unknown"):
        with pytest.raises(ValueError, match="Unknown"):
            load_profile(name)


def test_search_normalization_and_exact_backend():
    calls = []

    class Fake:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def text(self, query, **kwargs):
            calls.append((query, kwargs))
            return [None, {"title": "bad", "href": "file:///etc/passwd", "body": "bad"}] + [
                {"title": " T " + "x" * 300, "href": "https://example.com", "body": "b" * 2000}
            ] * 8

        def close(self):
            calls.append("closed")

    async def run():
        search = DuckDuckGoSearch(factory=Fake)
        result = await search.web_search(" query ")
        assert len(result) == 5
        assert len(result[0].title) == 200
        assert len(result[0].snippet) == 1000
        assert result[0].url == "https://example.com"
        await search.aclose()

    asyncio.run(run())
    assert calls == [{"timeout": 10}, ("query", {"backend": "duckduckgo", "max_results": 5}), "closed"]


@pytest.mark.parametrize("rows", [[], [{}], [{"title": 3}], [{"title": "x", "href": "https://u:p@example.com", "body": "x"}], None])
def test_unusable_search_is_typed(rows):
    class Fake:
        def __init__(self, **kwargs):
            pass

        def text(self, *args, **kwargs):
            return rows

    async def run():
        with pytest.raises(ResearchFailure, match="Research unavailable"):
            await DuckDuckGoSearch(factory=Fake).web_search("query")
    asyncio.run(run())


def test_query_validation_and_provider_errors():
    class Fake:
        def __init__(self, **kwargs):
            pass

        def text(self, *args, **kwargs):
            raise TimeoutError("secret blocked 429 provider details")

    async def run():
        search = DuckDuckGoSearch(factory=Fake)
        for query in ("", "  ", "x" * 501, None):
            with pytest.raises(ResearchFailure, match="Invalid research query"):
                await search.web_search(query)
        with pytest.raises(ResearchFailure) as error:
            await search.web_search("query")
        assert str(error.value) == "Research unavailable"
    asyncio.run(run())


def test_cancellation_holds_concurrency_slot_until_thread_finishes():
    entered, release = threading.Event(), threading.Event()
    calls = []

    class Fake:
        def __init__(self, **kwargs):
            pass

        def text(self, query, **kwargs):
            calls.append(query)
            entered.set()
            assert release.wait(5)
            return [{"title": "T", "href": "https://example.com", "body": "B"}]

    async def run():
        search = DuckDuckGoSearch(factory=Fake)
        first = asyncio.create_task(search.web_search("first"))
        await asyncio.to_thread(entered.wait, 5)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(search.web_search("second"))
        await asyncio.sleep(0)
        assert calls == ["first"]
        release.set()
        await second
        await search.aclose()
        assert calls == ["first", "second"]
    asyncio.run(run())


def test_native_local_chat_is_keyless_and_closes(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "unrelated-secret")
    monkeypatch.setenv("CFBD_API_KEY", "private-cfbd")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"model": "fixture", "message": {"role": "assistant", "content": "ok"}, "done": True})

    async def run():
        settings = Settings(_env_file=None, ollama_host="http://fixture:11434", ollama_model="fixture")
        async with local_model_client(settings, transport=httpx.MockTransport(respond)) as client:
            result = await client.chat(model=settings.ollama_model, messages=[{"role": "user", "content": "test"}])
            assert result.message.content == "ok"
            assert client._client.timeout.connect == 10
            assert client._client.timeout.read == 180
        assert client._client.is_closed
    asyncio.run(run())
    assert len(requests) == 1
    assert str(requests[0].url) == "http://fixture:11434/api/chat"
    assert not requests[0].headers.get("authorization")
    assert "secret" not in str(requests[0].headers)


def test_concurrent_agent_seed_preserves_existing(migrated_database):
    from sqlalchemy.orm import Session
    from app.models import Strategy
    from app.seed_strategy import AGENT_STRATEGY_ID, seed_agent_strategy

    engine, _ = migrated_database
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: seed_agent_strategy(engine), range(2))) == [False, True]
    with Session(engine) as session:
        record = session.get(Strategy, AGENT_STRATEGY_ID)
        assert record.config == {"profile": "FootballAnalysisExpert"}
        record.name = "Preserved"
        record.is_active = False
        session.commit()
    assert seed_agent_strategy(engine) is False
    with Session(engine) as session:
        record = session.get(Strategy, AGENT_STRATEGY_ID)
        assert record.name == "Preserved"
        assert record.is_active is False
