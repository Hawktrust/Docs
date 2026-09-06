"""Retrieval, with the provenance the Constitution requires captured at the point
of the fetch — not reconstructed afterwards.

Every retrieval records the exact URL fetched and the moment it was fetched.
Those two values travel with the payload all the way to the attribution record.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

import requests


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


def fetch(url: str, timeout: int = 30) -> Retrieval:
    retrieved_at = datetime.now(timezone.utc)
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "CrownAI-Ingest/0.1 (Ticket 01 thin loop)"},
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
