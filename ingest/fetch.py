"""Retrieval, with the provenance the Constitution requires captured at the point
of the fetch — not reconstructed afterwards.

Every retrieval records the exact URL fetched and the moment it was fetched.
Those two values travel with the payload all the way to the attribution record.
"""
import threading
import time
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

import requests


class DisallowedByRobots(Exception):
    """robots.txt says not to fetch this. The minimum courtesy, enforced.

    Separate from the register's terms position: the register records what the
    licence says, robots.txt records what the site operator asks of crawlers
    today. Both have to allow it.
    """


class RetrievalBlocked(Exception):
    """The fetch did not reach the source. No payload, so nothing to ingest.

    Raised rather than swallowed: a failed retrieval must never be papered over
    with placeholder data.
    """


@dataclass(frozen=True)
class Retrieval:
    url: str
    retrieved_at: datetime
    status_code: int
    body: str
    content_type: str
    # What the source offered for asking "has this changed?" later. Opaque
    # values, stored and replayed verbatim; see migration 0028.
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True)
class NotModified:
    """The source says the document we already hold is still current.

    Deliberately not a Retrieval. Nothing was retrieved, there is no body, and a
    caller that wanted one must not be able to treat this as though it got one —
    the whole value of a 304 is that it lets last_verified_at move *without*
    anything claiming a fetch happened.
    """
    url: str
    checked_at: datetime
    etag: str | None = None
    last_modified: str | None = None


USER_AGENT = "CrownAI-Ingest/0.1 (Ticket 01 thin loop)"

# Parsed robots files, so one poll does not re-fetch robots.txt per URL.
_robots: dict[str, urllib.robotparser.RobotFileParser] = {}

# One pooled connection per host, reused for robots.txt and for every page.
#
# Every retrieval used to open its own TCP connection and complete its own TLS
# handshake. Measured against the live amendment host on 2026-09-27 that cost
# 1,948 ms per request against 1,011 ms over a reused connection — 48% of the
# time spent on a handshake the previous request had already paid for. A poll of
# one LGA does it once per lead; a statewide re-verification would do it
# thousands of times. robots.txt shares the session deliberately: it is on the
# same origin, so fetching it warms the connection the page then travels over.
#
# Sessions are not thread-safe. Ingestion is a single-threaded CLI; a concurrent
# fetcher must build its own session per worker rather than borrow this one.
_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


def robots_allows(url: str, *, timeout: int = 10) -> bool:
    """Whether this site's robots.txt permits us to fetch this path.

    A robots.txt that cannot be fetched is treated as permission — that is the
    convention, and the register's terms position is the control that matters
    for anything Crown actually ingests.
    """
    parts = urlparse(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    parser = _robots.get(origin)
    if parser is None:
        robots_url = urlunparse((parts.scheme, parts.netloc, "/robots.txt", "", "", ""))
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        try:
            response = _session.get(robots_url, timeout=timeout)
            parser.parse(response.text.splitlines() if response.status_code == 200 else [])
        except requests.RequestException:
            parser.parse([])
        _robots[origin] = parser
    return parser.can_fetch(USER_AGENT, url)


def _get(session: requests.Session, url: str, *, timeout: int,
         etag: str | None = None, last_modified: str | None = None
         ) -> "Retrieval | NotModified":
    """Make the request and decide what the response means.

    Shared by the serial and the concurrent path so that "what a 304 means" is
    answered once. Two copies of this would be two chances to disagree about
    whether a record may have its verification date moved.
    """
    # Sent per request, not set on the session: a validator belongs to one
    # document, and leaving it on the session would ask about the wrong page.
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    retrieved_at = datetime.now(timezone.utc)
    try:
        response = session.get(url, timeout=timeout, headers=headers or None)
    except requests.RequestException as exc:
        raise RetrievalBlocked(f"GET {url} failed: {exc}") from exc

    if response.status_code == 304:
        # Only reachable when we asked conditionally. A server answering 304 to
        # an unconditional GET is misbehaving, and treating it as "unchanged"
        # would refresh a verification date on no evidence at all.
        if not headers:
            raise RetrievalBlocked(
                f"GET {url} returned 304 without a conditional request; nothing "
                "was asked, so nothing was confirmed")
        return NotModified(
            url=url, checked_at=retrieved_at,
            # A 304 may reissue the validators. Keep the new ones when it does,
            # so the next question is asked with what the server last said.
            etag=response.headers.get("etag") or etag,
            last_modified=response.headers.get("last-modified") or last_modified,
        )

    if response.status_code != 200:
        raise RetrievalBlocked(f"GET {url} returned HTTP {response.status_code}")

    return Retrieval(
        url=url,
        retrieved_at=retrieved_at,
        status_code=response.status_code,
        body=response.text,
        content_type=response.headers.get("content-type", ""),
        etag=response.headers.get("etag"),
        last_modified=response.headers.get("last-modified"),
    )


def fetch(url: str, timeout: int = 30, *, check_robots: bool = True,
          etag: str | None = None, last_modified: str | None = None
          ) -> Retrieval | NotModified:
    """Retrieve a URL, or learn from the source that it has not changed.

    Passing the etag or last_modified a previous retrieval recorded turns this
    into a conditional request, and a 304 comes back as NotModified rather than
    as a Retrieval with an empty body. Without them it is an ordinary GET, so
    every existing caller keeps getting a Retrieval or an exception.
    """
    if check_robots and not robots_allows(url):
        raise DisallowedByRobots(
            f"robots.txt at {urlparse(url).netloc} disallows {USER_AGENT} for {url}")
    return _get(_session, url, timeout=timeout, etag=etag,
                last_modified=last_modified)


# ------------------------------------------------- many at once, politely

# The smallest gap between two requests to one host when fetching concurrently.
# Not a performance number: it is what stops eight workers arriving at a
# council's web server as eight simultaneous requests. A publisher whose terms
# permit us to read their pages has not agreed to be hammered, and the register's
# position on those terms is the thing this project spends its credibility on.
DEFAULT_MIN_INTERVAL_SECONDS = 0.25


class _HostPacer:
    """Keeps requests to any one host at least min_interval apart.

    Per host, not global: fetching from four councils at once is four polite
    conversations, and pacing them against each other would slow the poll down
    for no one's benefit.
    """

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._next_allowed: dict[str, float] = {}

    def wait_for(self, url: str) -> None:
        if self._min_interval <= 0:
            return
        host = urlparse(url).netloc
        while True:
            with self._lock:
                now = time.monotonic()
                allowed = self._next_allowed.get(host, 0.0)
                if now >= allowed:
                    self._next_allowed[host] = now + self._min_interval
                    return
                delay = allowed - now
            # Slept outside the lock, so other hosts are not held up waiting for
            # this one's turn.
            time.sleep(delay)


def fetch_many(urls, *, workers: int = 4, timeout: int = 30,
               min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
               check_robots: bool = True, validators=None):
    """Fetch several URLs concurrently. Returns results in the order given.

    Each result is a Retrieval, a NotModified, or the exception that was raised
    for that URL — never a partial success, and never reordered, so a caller can
    zip results back onto whatever it was fetching them for.

    Concurrency lives here and nowhere else on purpose. Every worker builds its
    own requests.Session, because the module-level one is not thread-safe and
    sharing it would corrupt connection state under load. The database is not
    touched: callers fetch in parallel and then write serially, because a psycopg
    connection is not thread-safe either and an ingestion that half-wrote rows
    from four threads would be unreviewable.

    validators maps a URL to (etag, last_modified) to make its request
    conditional, so a re-verification pass can ask about many records at once.
    """
    urls = list(urls)
    if not urls:
        return []
    validators = validators or {}
    workers = max(1, min(workers, len(urls)))

    # robots.txt for every origin first, on this thread, through the shared
    # session. Serial on purpose: the parsed-robots cache is a plain dict, and
    # letting several workers populate it at once is a race for no gain — there
    # are a handful of origins and one fetch each.
    if check_robots:
        for url in urls:
            robots_allows(url)

    pacer = _HostPacer(min_interval_seconds)
    local = threading.local()

    def session() -> requests.Session:
        existing = getattr(local, "session", None)
        if existing is None:
            existing = requests.Session()
            existing.headers.update({"User-Agent": USER_AGENT})
            local.session = existing
        return existing

    def one(url):
        try:
            if check_robots and not robots_allows(url):
                raise DisallowedByRobots(
                    f"robots.txt at {urlparse(url).netloc} disallows {USER_AGENT} "
                    f"for {url}")
            etag, last_modified = validators.get(url, (None, None))
            pacer.wait_for(url)
            return _get(session(), url, timeout=timeout, etag=etag,
                        last_modified=last_modified)
        except Exception as exc:               # returned, not raised
            # One unreachable URL must not discard the ones that succeeded, and
            # it must not be silently dropped either — it comes back in place.
            return exc

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, urls))
