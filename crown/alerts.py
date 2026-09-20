"""Alerts: what changed, for whom, and whether it is worth saying.

The vision asks for a daily shortlist, a weekly brief and watchlist alerts, with
duplicates and low-confidence alerts suppressed. Three rules hold that together.

Nothing is raised twice. Every alert computes a dedupe key from what it is
about, and the database refuses a second one. "We already told you that" is the
difference between a product people read and one they filter to a folder.

Confidence is derived from the evidence, never asserted. An alert founded on a
search-relay lead is SPECULATIVE and stays unsent, because the Constitution says
rumours are never presented as facts.

Every alert carries the affected place, what happened, where that came from,
what it means and what to do next. An alert that cannot fill those is not an
alert; it is noise with a timestamp.
"""
import hashlib
from dataclasses import dataclass, field
from datetime import date

from . import audit

ACTOR_AGENT = "crown.alerts"

# Below this, an alert is recorded and suppressed rather than delivered.
DELIVERABLE_CONFIDENCE = ("CONFIRMED", "PROBABLE")

SUPPRESSED_LOW_CONFIDENCE = (
    "speculative: founded on evidence that was never directly verified")


@dataclass
class Raised:
    created: list = field(default_factory=list)
    duplicates: list = field(default_factory=list)
    suppressed: list = field(default_factory=list)

    def summary(self) -> str:
        return (f"raised {len(self.created)}, "
                f"suppressed {len(self.suppressed)}, "
                f"already known {len(self.duplicates)}")


def dedupe_key(kind: str, *parts) -> str:
    """One key per thing-we-might-say, so we only say it once."""
    material = "|".join([kind] + [str(p) for p in parts if p is not None])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def confidence_of_evidence(evidence_class: str, retrieval_method: str) -> str:
    """The same derivation the recommendation uses. One rule, one place."""
    if evidence_class == "FACT" and retrieval_method == "DIRECT_FETCH":
        return "CONFIRMED"
    if (evidence_class == "FACT" and retrieval_method == "OPERATOR_CAPTURE") or \
            (evidence_class == "HYPOTHESIS" and retrieval_method == "DIRECT_FETCH"):
        return "PROBABLE"
    return "SPECULATIVE"


def raise_alert(conn, *, kind: str, detected_event: str, source_url: str,
                confidence: str, investment_impact: str, recommended_action: str,
                key_parts: tuple, watchlist_id=None, user_id=None, lga=None,
                locality=None, parcel_id=None, acres=None, zone_code=None,
                overlay_codes=None, evidence_id=None, signal_id=None,
                correlation_id=None, report: Raised | None = None):
    """Raise one alert, unless it is a duplicate or too weakly founded."""
    key = dedupe_key(kind, *key_parts)
    report = report if report is not None else Raised()

    suppressed = None
    if confidence not in DELIVERABLE_CONFIDENCE:
        suppressed = SUPPRESSED_LOW_CONFIDENCE

    row = conn.execute(
        """INSERT INTO alert (kind, watchlist_id, user_id, lga, locality, parcel_id,
                   acres, zone_code, overlay_codes, detected_event, source_url,
                   evidence_id, signal_id, confidence, investment_impact,
                   recommended_action, dedupe_key, suppressed_reason)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (dedupe_key) DO NOTHING
           RETURNING id""",
        (kind, watchlist_id, user_id, lga, locality, parcel_id, acres, zone_code,
         list(overlay_codes or []), detected_event, source_url, evidence_id,
         signal_id, confidence, investment_impact, recommended_action, key,
         suppressed),
    ).fetchone()

    if row is None:
        report.duplicates.append(key)
        return None

    alert_id = row[0]
    (report.suppressed if suppressed else report.created).append(alert_id)
    audit.write(conn, correlation_id or audit.new_correlation_id(),
                "ALERT_SUPPRESSED" if suppressed else "ALERT_RAISED",
                "alert", alert_id,
                new_state={"kind": kind, "confidence": confidence,
                           "lga": lga, "locality": locality},
                evidence_id=evidence_id, actor_user_id=user_id,
                actor_agent=ACTOR_AGENT)
    return alert_id


# ------------------------------------------------------------------ detectors

def _watchers(conn, lga, locality):
    """Who asked to hear about this place."""
    return conn.execute(
        """SELECT id, user_id FROM watchlist
           WHERE is_active
             AND ((kind = 'LGA' AND target ILIKE %s)
               OR (kind = 'SUBURB' AND target ILIKE %s))""",
        (lga or "", locality or ""),
    ).fetchall()


def new_evidence(conn, report: Raised, correlation_id=None) -> Raised:
    """Amendments touching a watched geography."""
    rows = conn.execute(
        """SELECT e.id, e.lga, e.geography -> 'suburbs' ->> 0, e.title,
                  e.source_url, e.evidence_class::text, e.retrieval_method,
                  e.amendment_status, e.source_reference
           FROM evidence_record e
           WHERE e.origin = 'REAL'
             AND NOT EXISTS (SELECT 1 FROM alert a
                             WHERE a.evidence_id = e.id AND a.kind = 'NEW_EVIDENCE')"""
    ).fetchall()

    for (eid, lga, locality, title, url, klass, method, status, reference) in rows:
        confidence = confidence_of_evidence(klass, method)
        for watchlist_id, user_id in _watchers(conn, lga, locality):
            raise_alert(
                conn, kind="NEW_EVIDENCE", watchlist_id=watchlist_id, user_id=user_id,
                lga=lga, locality=locality, evidence_id=eid,
                detected_event=f"{reference}: {title}"
                               + (f" ({status})" if status else ""),
                source_url=url, confidence=confidence,
                investment_impact="a planning change affects a geography you watch; "
                                  "re-check the opportunities resting on it",
                recommended_action="open the evidence pack and confirm the stage",
                key_parts=(eid, watchlist_id), correlation_id=correlation_id,
                report=report)
    return report


def market_moves(conn, report: Raised, minimum_weight: float = 0.6,
                 correlation_id=None) -> Raised:
    """A developer, fund or government body moving in a watched geography."""
    rows = conn.execute(
        """SELECT s.id, s.lga, s.locality, s.signal_kind::text, s.detail,
                  s.source_url, w.weight,
                  CASE WHEN a.publishable_by_name THEN a.name END, a.kind::text
           FROM actor_signal s
           JOIN market_actor a ON a.id = s.actor_id
           JOIN signal_weight_config w
             ON w.signal_kind = s.signal_kind AND w.is_active
           WHERE s.origin = 'REAL' AND w.weight >= %s
             AND NOT EXISTS (SELECT 1 FROM alert al WHERE al.signal_id = s.id)""",
        (minimum_weight,),
    ).fetchall()

    for (sid, lga, locality, kind, detail, url, weight, name, actor_kind) in rows:
        # An unnamed actor is still reportable as an event; only the name is held
        # back. See crown/signals.py.
        who = name or f"an unnamed {actor_kind.replace('_', ' ').lower()}"
        for watchlist_id, user_id in _watchers(conn, lga, locality):
            raise_alert(
                conn, kind="MARKET_SIGNAL", watchlist_id=watchlist_id, user_id=user_id,
                lga=lga, locality=locality, signal_id=sid,
                detected_event=f"{who}: {detail}",
                source_url=url,
                # A disclosed, sourced corporate action is as confirmed as this
                # layer gets; anything weaker than the threshold never arrives.
                confidence="CONFIRMED" if float(weight) >= 0.8 else "PROBABLE",
                investment_impact="somebody with capital is acting in a geography "
                                  "you watch",
                recommended_action="check adjoining parcels and current mandates",
                key_parts=(sid, watchlist_id), correlation_id=correlation_id,
                report=report)
    return report


def government_acquisition(conn, report: Raised, correlation_id=None) -> Raised:
    """A Public Acquisition Overlay on land in a watched geography."""
    rows = conn.execute(
        """SELECT p.id, p.spi, p.lga, p.locality,
                  round((p.area_sqm / 4046.8564224)::numeric, 2),
                  pc.zone_code, pc.overlay_codes
           FROM parcel p JOIN parcel_planning_current pc ON pc.parcel_id = p.id
           WHERE p.origin = 'REAL' AND 'PAO' = ANY(pc.overlay_codes)"""
    ).fetchall()

    for (pid, spi, lga, locality, acres, zone, overlays) in rows:
        for watchlist_id, user_id in _watchers(conn, lga, locality):
            raise_alert(
                conn, kind="GOVERNMENT_ACQUISITION", watchlist_id=watchlist_id,
                user_id=user_id, lga=lga, locality=locality, parcel_id=pid,
                acres=acres, zone_code=zone, overlay_codes=overlays,
                detected_event=f"{spi} carries a Public Acquisition Overlay",
                source_url="planning scheme overlay",
                confidence="CONFIRMED",
                investment_impact="an authority has flagged an intention to acquire "
                                  "this land; compensation is at market value and "
                                  "the timing is not yours",
                recommended_action="treat as Avoid unless the acquisition itself is "
                                   "the thesis",
                key_parts=(pid, watchlist_id), correlation_id=correlation_id,
                report=report)
    return report


def stale_evidence(conn, report: Raised, correlation_id=None) -> Raised:
    """Records past their shelf life, so nothing rests on an unchecked fact."""
    rows = conn.execute(
        """SELECT id, source_reference, lga, title, source_url, retrieval_method,
                  days_since_verified, shelf_life_days
           FROM stale_evidence"""
    ).fetchall()

    for (eid, reference, lga, title, url, method, age, shelf) in rows:
        raise_alert(
            conn, kind="STALE_EVIDENCE", lga=lga, evidence_id=eid,
            detected_event=f"{reference} was last verified {age} days ago; "
                           f"a {method.replace('_', ' ').lower()} record goes "
                           f"stale after {shelf}",
            source_url=url,
            confidence="CONFIRMED",     # the staleness itself is a fact
            investment_impact="anything resting on this record is resting on an "
                              "unchecked fact",
            recommended_action="re-retrieve the source and update last_verified_at",
            key_parts=(eid, age // 30), correlation_id=correlation_id, report=report)
    return report


def data_rights_exceptions(conn, report: Raised, correlation_id=None) -> Raised:
    """A source in use without a complete register entry."""
    for code, _, _, _, reason, _ in conn.execute(
        """SELECT code, display_name, provider, lane::text, exception_reason, notes
           FROM data_rights_exception""").fetchall():
        raise_alert(
            conn, kind="DATA_RIGHTS_EXCEPTION",
            detected_event=f"{code}: {reason}",
            source_url="data rights register",
            confidence="CONFIRMED",
            investment_impact="a source is being used without a complete entry; "
                              "this should be empty before go-live",
            recommended_action="complete the register entry or stop ingesting",
            key_parts=(code, reason), correlation_id=correlation_id, report=report)
    return report


DETECTORS = (new_evidence, market_moves, government_acquisition,
             stale_evidence, data_rights_exceptions)


def run(conn, correlation_id=None) -> Raised:
    """Every detector, one pass. Caller commits."""
    correlation_id = correlation_id or audit.new_correlation_id()
    report = Raised()
    for detector in DETECTORS:
        detector(conn, report, correlation_id=correlation_id)
    audit.write(conn, correlation_id, "ALERT_RUN_COMPLETED", "alert", "run",
                new_state={"raised": len(report.created),
                           "suppressed": len(report.suppressed),
                           "duplicates": len(report.duplicates)},
                actor_agent=ACTOR_AGENT)
    return report


def pending(conn, user_id=None, limit: int = 100):
    """Deliverable alerts nobody has sent yet."""
    sql = """SELECT id, kind::text, lga, locality, detected_event, source_url,
                    confidence::text, investment_impact, recommended_action,
                    acres, zone_code, overlay_codes, created_at
             FROM alert
             WHERE delivered_at IS NULL AND suppressed_reason IS NULL"""
    params: list = []
    if user_id:
        sql += " AND (user_id = %s OR user_id IS NULL)"
        params.append(user_id)
    return conn.execute(sql + " ORDER BY created_at DESC LIMIT %s",
                        params + [limit]).fetchall()


def mark_delivered(conn, alert_ids, correlation_id=None) -> int:
    if not alert_ids:
        return 0
    conn.execute(
        """UPDATE alert SET delivered_at = now()
           WHERE id = ANY(%s) AND delivered_at IS NULL AND suppressed_reason IS NULL""",
        (list(alert_ids),))
    audit.write(conn, correlation_id or audit.new_correlation_id(),
                "ALERTS_DELIVERED", "alert", "batch",
                new_state={"count": len(alert_ids)}, actor_agent=ACTOR_AGENT)
    return len(alert_ids)


def daily_shortlist(conn, as_of: date | None = None, limit: int = 20):
    """The highest-scoring geographies with something new to say today."""
    from . import signals
    ranked = signals.hotspots(conn, as_of=as_of, limit=limit)
    fresh = {(row[2], row[3]) for row in pending(conn)}
    return [h for h in ranked if (h.lga, h.locality) in fresh] or ranked[:limit]
