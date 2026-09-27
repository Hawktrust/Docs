"""Fetching several pages at once, and the things that must stay true when it does.

Concurrency is opt-in and confined to ingest.fetch.fetch_many. These tests hold
the three properties that make it safe to turn on: results stay in the order they
were asked for, one failure does not discard the successes, and no host is served
more requests per second because the worker count went up.

Nothing here touches the database. That is the design: pages are retrieved in
parallel and written serially, because a psycopg connection is not thread-safe.
"""
import threading
import time

import pytest

from ingest import fetch as fetch_module
from ingest.fetch import NotModified, Retrieval, RetrievalBlocked


class Response:
    def __init__(self, url, status=200, headers=None, text="<html></html>"):
        self.url = url
        self.status_code = status
        self.headers = headers or {"content-type": "text/html"}
        self.text = text
        # A real requests.Response carries the undecoded bytes too, and
        # Retrieval keeps them so a PDF can be read. A stub without them stops
        # standing in for the thing it is standing in for.
        self.content = text.encode()


@pytest.fixture(autouse=True)
def allow_everything(monkeypatch):
    """robots.txt is a separate concern with its own tests."""
    monkeypatch.setattr(fetch_module, "robots_allows", lambda url, **k: True)


def stub_sessions(monkeypatch, handler):
    """Make every worker's Session use handler, and record which sessions appear."""
    seen_sessions = []

    class StubSession:
        def __init__(self):
            self.headers = {}
            seen_sessions.append(self)

        def get(self, url, timeout=30, headers=None):
            return handler(url, headers)

    monkeypatch.setattr(fetch_module.requests, "Session", StubSession)
    return seen_sessions


# ------------------------------------------------------------------- ordering

def test_results_come_back_in_the_order_they_were_asked_for(monkeypatch):
    """A caller zips these onto the leads it fetched them for."""
    urls = [f"https://a.test/{n}" for n in range(12)]

    def handler(url, headers):
        # finish out of order on purpose
        time.sleep(0.02 if url.endswith("0") else 0.001)
        return Response(url)

    stub_sessions(monkeypatch, handler)
    results = fetch_module.fetch_many(urls, workers=6, min_interval_seconds=0)

    assert [r.url for r in results] == urls


def test_an_empty_list_asks_for_nothing(monkeypatch):
    stub_sessions(monkeypatch, lambda url, headers: Response(url))
    assert fetch_module.fetch_many([], workers=4) == []


# ------------------------------------------------------------------- failures

def test_one_unreachable_url_does_not_discard_the_others(monkeypatch):
    """The failure comes back in place, so nothing is silently dropped."""
    urls = ["https://a.test/ok1", "https://a.test/bad", "https://a.test/ok2"]

    def handler(url, headers):
        if url.endswith("bad"):
            return Response(url, status=403)
        return Response(url)

    stub_sessions(monkeypatch, handler)
    results = fetch_module.fetch_many(urls, workers=3, min_interval_seconds=0)

    assert isinstance(results[0], Retrieval)
    assert isinstance(results[1], RetrievalBlocked)
    assert "403" in str(results[1])
    assert isinstance(results[2], Retrieval)


def test_a_robots_refusal_is_reported_per_url_not_raised(monkeypatch):
    urls = ["https://a.test/allowed", "https://a.test/private"]
    monkeypatch.setattr(fetch_module, "robots_allows",
                        lambda url, **k: not url.endswith("private"))
    stub_sessions(monkeypatch, lambda url, headers: Response(url))

    results = fetch_module.fetch_many(urls, workers=2, min_interval_seconds=0)
    assert isinstance(results[0], Retrieval)
    assert isinstance(results[1], fetch_module.DisallowedByRobots)


# ---------------------------------------------------------------- the sessions

def test_workers_do_not_share_the_module_session(monkeypatch):
    """requests.Session is not thread-safe; sharing one corrupts connection state."""
    stub_sessions(monkeypatch, lambda url, headers: Response(url))
    module_session = fetch_module._session

    used = []

    class Recording:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=30, headers=None):
            used.append(self)
            return Response(url)

    monkeypatch.setattr(fetch_module.requests, "Session", Recording)
    fetch_module.fetch_many([f"https://a.test/{n}" for n in range(8)],
                            workers=4, min_interval_seconds=0)

    assert used, "the workers made requests"
    assert module_session not in used, "no worker borrowed the shared session"


# ---------------------------------------------------------------- politeness

def test_requests_to_one_host_stay_spaced_apart(monkeypatch):
    """Eight workers must not become eight simultaneous requests to one server."""
    starts = []
    lock = threading.Lock()

    def handler(url, headers):
        with lock:
            starts.append(time.monotonic())
        return Response(url)

    stub_sessions(monkeypatch, handler)
    interval = 0.05
    fetch_module.fetch_many([f"https://one.test/{n}" for n in range(6)],
                            workers=6, min_interval_seconds=interval)

    starts.sort()
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    # Allow scheduling slop, but the requests must clearly be paced rather than
    # all arriving together.
    assert all(g >= interval * 0.7 for g in gaps), gaps
    assert starts[-1] - starts[0] >= interval * (len(starts) - 1) * 0.7


def test_separate_hosts_are_not_paced_against_each_other(monkeypatch):
    """Four councils at once is four polite conversations, not one queue."""
    stub_sessions(monkeypatch, lambda url, headers: Response(url))
    urls = [f"https://host{n}.test/page" for n in range(6)]

    began = time.monotonic()
    fetch_module.fetch_many(urls, workers=6, min_interval_seconds=0.2)
    elapsed = time.monotonic() - began

    # Paced per host, these are six different hosts, so they should overlap
    # rather than serialise into 6 x 0.2s.
    assert elapsed < 0.2 * len(urls) * 0.5, elapsed


# -------------------------------------------------------------- conditionally

def test_validators_make_individual_requests_conditional(monkeypatch):
    """A re-verification pass asks about many records at once, each with its own
    question."""
    asked = {}

    def handler(url, headers):
        asked[url] = dict(headers or {})
        if url.endswith("unchanged"):
            return Response(url, status=304, headers={})
        return Response(url)

    stub_sessions(monkeypatch, handler)
    urls = ["https://a.test/unchanged", "https://a.test/plain"]
    results = fetch_module.fetch_many(
        urls, workers=2, min_interval_seconds=0,
        validators={"https://a.test/unchanged": ('"e1"', None)})

    assert asked["https://a.test/unchanged"]["If-None-Match"] == '"e1"'
    assert asked["https://a.test/plain"] == {}
    assert isinstance(results[0], NotModified)
    assert isinstance(results[1], Retrieval)


def test_concurrency_actually_overlaps(monkeypatch):
    """Otherwise none of the above is worth the thread pool."""
    def handler(url, headers):
        time.sleep(0.05)
        return Response(url)

    stub_sessions(monkeypatch, handler)
    urls = [f"https://a.test/{n}" for n in range(8)]

    began = time.monotonic()
    fetch_module.fetch_many(urls, workers=8, min_interval_seconds=0)
    concurrent = time.monotonic() - began

    assert concurrent < 0.05 * len(urls) * 0.6, concurrent
