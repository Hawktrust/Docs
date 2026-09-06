"""SIGNAL -> EVIDENCE, the first leg of the thin loop.

One run does, per amendment:

  1. land the raw payload in raw_ingest, keyed so a re-run cannot duplicate it
  2. validate provenance
  3. write an evidence_record, or route the failure to evidence_review_queue
  4. write one audit row per state transition

A duplicate payload short-circuits at step 1: no second evidence record, no
second audit row beyond the skip itself.
"""
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from . import provenance
from .adapters import vic_planning

ACTOR_AGENT = "ingest.pipeline"


@dataclass
class RunReport:
    correlation_id: str
    source_code: str
    lga: str
    retrieved_from: str | None = None
    retrieved_at: datetime | None = None
    ingested: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    review_queued: list[tuple[str, list[str]]] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"correlation {self.correlation_id}\n"
            f"source      {self.source_code}\n"
            f"lga         {self.lga}\n"
            f"retrieved   {self.retrieved_from} at {self.retrieved_at}\n"
            f"ingested    {len(self.ingested)} {self.ingested}\n"
            f"duplicates  {len(self.duplicates)} {self.duplicates}\n"
            f"to review   {len(self.review_queued)} {self.review_queued}"
        )


def content_hash(item: dict) -> str:
    """sha256 over the normalised payload, key order fixed so the hash is stable."""
    canonical = json.dumps(item, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _audit(conn, correlation_id, action, object_table, object_id,
           new_state=None, evidence_id=None):
    conn.execute(
        """
        INSERT INTO audit_event (actor_agent, action, object_table, object_id,
                                 new_state, evidence_id, correlation_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (ACTOR_AGENT, action, object_table, str(object_id),
         Jsonb(new_state) if new_state is not None else None,
         evidence_id, correlation_id),
    )


def ingest(conn, source, retrieval, payload: list[dict], lga: str) -> RunReport:
    """Run the ingestion for one LGA. Caller commits."""
    correlation_id = str(uuid.uuid4())
    report = RunReport(
        correlation_id=correlation_id,
        source_code=source.code,
        lga=lga,
        retrieved_from=retrieval.url,
        retrieved_at=retrieval.retrieved_at,
    )

    scoped = [i for i in payload if (i.get("lga") or "").strip().lower() == lga.strip().lower()]
    records = vic_planning.from_json(scoped, retrieval, source)

    for item, record in zip(scoped, records):
        source_ref = record.get("source_ref") or ""
        digest = content_hash(item)

        # 1. land the raw payload. The unique constraint makes the re-run a no-op.
        raw = conn.execute(
            """
            INSERT INTO raw_ingest (source_id, source_ref, content_hash, payload,
                                    retrieved_at, retrieved_from)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_id, source_ref, content_hash) DO NOTHING
            RETURNING id
            """,
            (source.id, source_ref, digest, Jsonb(item),
             retrieval.retrieved_at, retrieval.url),
        ).fetchone()

        if raw is None:
            report.duplicates.append(source_ref)
            _audit(conn, correlation_id, "INGEST_SKIPPED_DUPLICATE",
                   "raw_ingest", source_ref, {"content_hash": digest})
            continue

        raw_id = raw[0]
        _audit(conn, correlation_id, "RAW_INGESTED", "raw_ingest", raw_id,
               {"source_ref": source_ref, "content_hash": digest})

        # 2. provenance validation
        gaps = provenance.missing_fields(record)
        if gaps:
            # 3a. failures go to the review queue, never into the graph
            queued = conn.execute(
                """
                INSERT INTO evidence_review_queue (raw_ingest_id, source_id,
                            attempted_payload, failure_reason, missing_fields)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
                """,
                (raw_id, source.id, Jsonb(item),
                 "missing mandatory provenance field(s)", gaps),
            ).fetchone()[0]
            report.review_queued.append((source_ref or "<no reference>", gaps))
            _audit(conn, correlation_id, "EVIDENCE_REJECTED_TO_REVIEW",
                   "evidence_review_queue", queued, {"missing_fields": gaps})
            continue

        # 3b. provenance complete: into the graph
        evidence_id = conn.execute(
            """
            INSERT INTO evidence_record (
                raw_ingest_id, source_id, source_reference, source_url, provider,
                retrieved_at, observed_at, last_verified_at, lane, reliability,
                evidence_class, confidence, lga, title, summary, amendment_status,
                geography)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (raw_id, source.id, record["source_reference"], record["source_url"],
             record["provider"], record["retrieved_at"], record["observed_at"],
             record["last_verified_at"], record["lane"], record["reliability"],
             record["evidence_class"], record["confidence"], record["lga"],
             record["title"], record["summary"], record["amendment_status"],
             Jsonb(record["geography"]) if record["geography"] else None),
        ).fetchone()[0]

        report.ingested.append(source_ref)
        _audit(conn, correlation_id, "EVIDENCE_CREATED", "evidence_record",
               evidence_id,
               {"evidence_class": record["evidence_class"],
                "amendment_status": record["amendment_status"]},
               evidence_id=evidence_id)

    return report
