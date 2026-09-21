"""Operator capture: a named human retrieves the page the system cannot reach.

The build environment's egress policy refuses every Victorian planning host. A
person with a browser is not so constrained, and that is a real channel rather
than a workaround: the publisher's own page, opened by a named human, with the
bytes kept.

What makes it evidence rather than hearsay:

  the bytes are retained      capture_artifact stores the raw HTML, so any
                              record drawn from it can be rechecked against
                              what was actually on the page

  the bytes are fingerprinted the bundle carries a sha256 that is recomputed on
                              import; a bundle whose hash does not match its
                              own content is refused

  a person is on the hook     captured_by names them, and the operator has to
                              confirm each field rather than accept whatever a
                              parser guessed

Migration 0006 grades it accordingly: OPERATOR_CAPTURE may be STRONG, so a
gazetted amendment captured this way can be a FACT, but never AUTHORITATIVE.
That stays reserved for a fetch the system made and can make again.
"""
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from crown import audit

from . import provenance
from .adapters import vic_planning

ACTOR_AGENT = "ingest.capture"
RELIABILITY = "STRONG"


class BadCapture(Exception):
    """The bundle is not internally consistent, so none of it is trusted."""


@dataclass
class CaptureReport:
    correlation_id: str
    capture_id: str | None = None
    source_url: str = ""
    sha256: str = ""
    ingested: list = field(default_factory=list)
    review_queued: list = field(default_factory=list)
    leads_resolved: list = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"correlation  {self.correlation_id}\n"
            f"captured     {self.source_url}\n"
            f"sha256       {self.sha256}\n"
            f"ingested     {len(self.ingested)} {self.ingested}\n"
            f"to review    {len(self.review_queued)} {self.review_queued}\n"
            f"leads closed {len(self.leads_resolved)} {self.leads_resolved}"
        )


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load(path: str) -> dict:
    with open(path) as fh:
        return json.load(fh)


def validate(bundle: dict) -> None:
    """Refuse a bundle that does not hold together. Checked before anything is written."""
    capture = bundle.get("capture") or {}
    for required in ("source_url", "captured_at", "raw_html", "sha256"):
        if not capture.get(required):
            raise BadCapture(f"capture is missing {required}")

    actual = sha256_of(capture["raw_html"])
    if actual != capture["sha256"]:
        raise BadCapture(
            "the bundle's sha256 does not match its own raw_html "
            f"(states {capture['sha256'][:16]}..., computes {actual[:16]}...); "
            "the capture has been altered since it was taken"
        )

    if not bundle.get("confirmed_by_operator"):
        raise BadCapture(
            "the operator has not confirmed the extracted fields; a capture is "
            "only as good as the person who checked it"
        )

    if not bundle.get("records"):
        raise BadCapture("the capture contains no amendment records")


def ingest_capture(conn, source, bundle: dict, operator_id, *,
                   correlation_id=None) -> CaptureReport:
    """Store the bytes, then the records drawn from them. Caller commits."""
    validate(bundle)
    correlation_id = correlation_id or audit.new_correlation_id()
    capture = bundle["capture"]
    report = CaptureReport(correlation_id=correlation_id,
                           source_url=capture["source_url"],
                           sha256=capture["sha256"])

    captured_at = _parse_timestamp(capture["captured_at"])

    # The same page captured twice is one artifact, not two.
    existing = conn.execute(
        "SELECT id FROM capture_artifact WHERE sha256 = %s", (capture["sha256"],)
    ).fetchone()
    if existing:
        capture_id = existing[0]
    else:
        capture_id = conn.execute(
            """INSERT INTO capture_artifact (source_id, captured_by, captured_at,
                       source_url, sha256, byte_length, raw_html, page_title)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (source.id, operator_id, captured_at, capture["source_url"],
             capture["sha256"], len(capture["raw_html"].encode("utf-8")),
             capture["raw_html"], capture.get("page_title")),
        ).fetchone()[0]
        audit.write(conn, correlation_id, "PAGE_CAPTURED", "capture_artifact",
                    capture_id,
                    new_state={"source_url": capture["source_url"],
                               "sha256": capture["sha256"]},
                    actor_user_id=operator_id, actor_agent=ACTOR_AGENT)
    report.capture_id = capture_id

    for item in bundle["records"]:
        record = _to_evidence(item, capture, captured_at, source)
        gaps = provenance.missing_fields(record)
        if gaps:
            queue_id = conn.execute(
                """INSERT INTO evidence_review_queue (source_id, attempted_payload,
                           failure_reason, missing_fields)
                   VALUES (%s,%s,%s,%s) RETURNING id""",
                (source.id, Jsonb(item),
                 "captured from the source, but the operator did not confirm every "
                 "mandatory provenance field", gaps),
            ).fetchone()[0]
            report.review_queued.append((item.get("amendment_number"), gaps))
            audit.write(conn, correlation_id, "EVIDENCE_REJECTED_TO_REVIEW",
                        "evidence_review_queue", queue_id,
                        new_state={"missing_fields": gaps},
                        actor_user_id=operator_id, actor_agent=ACTOR_AGENT)
            continue

        evidence_id = conn.execute(
            """
            INSERT INTO evidence_record (
                source_id, source_reference, source_url, provider, retrieved_at,
                observed_at, last_verified_at, lane, reliability, evidence_class,
                confidence, lga, title, summary, amendment_status, geography,
                retrieval_method, captured_by, capture_sha256)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    'OPERATOR_CAPTURE',%s,%s)
            RETURNING id
            """,
            (source.id, record["source_reference"], record["source_url"],
             record["provider"], record["retrieved_at"], record["observed_at"],
             record["last_verified_at"], record["lane"], record["reliability"],
             record["evidence_class"], record["confidence"], record["lga"],
             record["title"], record.get("summary"), record.get("amendment_status"),
             Jsonb(record["geography"]) if record.get("geography") else None,
             operator_id, capture["sha256"]),
        ).fetchone()[0]

        report.ingested.append(record["source_reference"])
        audit.write(conn, correlation_id, "EVIDENCE_CREATED", "evidence_record",
                    evidence_id,
                    new_state={"evidence_class": record["evidence_class"],
                               "retrieval_method": "OPERATOR_CAPTURE",
                               "capture_sha256": capture["sha256"]},
                    evidence_id=evidence_id, actor_user_id=operator_id,
                    actor_agent=ACTOR_AGENT)

        # A capture answers any lead that was waiting on this amendment.
        resolved = conn.execute(
            """UPDATE evidence_review_queue SET resolved_at = now(), resolved_by = %s
               WHERE resolved_at IS NULL
                 AND attempted_payload ->> 'amendment_number' = %s
               RETURNING id""",
            (operator_id, record["source_reference"]),
        ).fetchall()
        for (queue_id,) in resolved:
            report.leads_resolved.append(record["source_reference"])
            audit.write(conn, correlation_id, "LEAD_RESOLVED_BY_CAPTURE",
                        "evidence_review_queue", queue_id,
                        new_state={"evidence_id": str(evidence_id)},
                        evidence_id=evidence_id, actor_user_id=operator_id,
                        actor_agent=ACTOR_AGENT)

    return report


def _to_evidence(item: dict, capture: dict, captured_at, source) -> dict:
    evidence_class = vic_planning.classify(item.get("status"))
    return {
        "source_reference": item.get("amendment_number"),
        "source_url": item.get("detail_url") or capture["source_url"],
        "provider": source.provider,
        "retrieved_at": captured_at,
        "observed_at": vic_planning._parse_date(item.get("observed_at")),
        "last_verified_at": captured_at,
        "lane": source.lane,
        "reliability": RELIABILITY,
        "evidence_class": evidence_class,
        "confidence": vic_planning.CONFIDENCE.get(evidence_class,
                                                  vic_planning.DEFAULT_CONFIDENCE),
        "lga": item.get("lga"),
        "title": item.get("title"),
        "summary": item.get("summary"),
        "amendment_status": item.get("status"),
        "geography": item.get("geography"),
    }


def _parse_timestamp(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
