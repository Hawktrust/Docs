"""Retrieval, with the provenance the Constitution requires captured at the point
of the fetch — not reconstructed afterwards.

Every retrieval records the exact URL fetched and the moment it was fetched.
Those two values travel with the payload all the way to the attribution record.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

import urllib.robotparser
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


USER_AGENT = "CrownAI-Ingest/0.1 (Ticket 01 thin loop)"

# Parsed robots files, so one poll does not re-fetch robots.txt per URL.
_robots: dict[str, urllib.robotparser.RobotFileParser] = {}


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
            response = requests.get(robots_url, timeout=timeout,
                                    headers={"User-Agent": USER_AGENT})
            parser.parse(response.text.splitlines() if response.status_code == 200 else [])
        except requests.RequestException:
            parser.parse([])
        _robots[origin] = parser
    return parser.can_fetch(USER_AGENT, url)


def fetch(url: str, timeout: int = 30, *, check_robots: bool = True) -> Retrieval:
    if check_robots and not robots_allows(url):
        raise DisallowedByRobots(
            f"robots.txt at {urlparse(url).netloc} disallows {USER_AGENT} for {url}")

    retrieved_at = datetime.now(timezone.utc)
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        )
    except requests.RequestException as exc:
        raise RetrievalBlocked(f"GET {url} failed: {exc}") from exc

    if response.status_code != 200:
        raise RetrievalBlocked(f"GET {url} returned HTTP {response.status_code}")

    return Retrieval(
        url=url,
        retrieved_at=retrieved_at,
        status_code=response.status_code,
        body=response.text,
        content_type=response.headers.get("content-type", ""),
    )
