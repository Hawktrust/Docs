"""Where money is moving, from what is published.

Three questions, three answers, and the difference between them matters.

  big firms          Listed developers disclose material acquisitions to the ASX
                     and publish landbank tables by region. They lodge permits,
                     appear at panels, make PSP submissions. All public, all
                     earlier than a title transfer.

  government         Already in the data. A Public Acquisition Overlay marks land
                     an authority proposes to acquire, and it sits in the overlay
                     list the land layer already holds. See government_intent().

  buyer agents       Their buying is client-confidential and will stay that way.
                     Their recommendations are public — and are opinion, not
                     action. Weighted lowest of everything here, because a suburb
                     reaching a hotspot list is the end of a move, not the start.

Elected officials count toward a geography and are never named. Registers of
interests are published so the public can scrutinise the people in them, which
is not what Crown is doing with them; the aggregate is a fair read, a named
politician in a prospecting brief is not.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import audit

ACTOR_AGENT = "crown.signals"

# A signal stops counting after two years, linearly. Land cycles are slow, but
# a five-year-old permit application is history rather than intent.
SIGNAL_HORIZON = timedelta(days=730)


@dataclass
class Contribution:
    signal_kind: str
    weight: float
    recency: float
    actor_name: str | None       # None where the actor may not be named
    actor_kind: str
    detail: str
    source_url: str
    observed_at: date

    @property
    def score(self) -> float:
        return self.weight * self.recency


@dataclass
class Hotspot:
    lga: str
    locality: str | None
    score: float
    signal_count: int
    contributions: list[Contribution] = field(default_factory=list)

    @property
    def named_actors(self) -> list[str]:
        """Actors that may be shown with a name against them."""
        return sorted({c.actor_name for c in self.contributions if c.actor_name})

    @property
    def unnamed_count(self) -> int:
        """Signals counted but not attributable in output."""
        return sum(1 for c in self.contributions if c.actor_name is None)

    def by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for c in self.contributions:
            counts[c.signal_kind] = counts.get(c.signal_kind, 0) + 1
        return counts


def active_weights(conn) -> dict[str, float]:
    rows = conn.execute(
        """SELECT signal_kind::text, weight FROM signal_weight_config
           WHERE is_active""").fetchall()
    if not rows:
        raise RuntimeError(
            "no active signal weights: these are configuration and the ranking "
            "will not invent them")
    return {kind: float(weight) for kind, weight in rows}


def record(conn, *, actor_id, signal_kind: str, lga: str, locality: str | None,
           observed_at: date, source_id, source_url: str, retrieved_at,
           detail: str, evidence_id=None, origin: str = "REAL",
           correlation_id=None) -> str:
    """Record one observation. Caller commits."""
    if not detail or not detail.strip():
        raise ValueError("a signal says what was observed")
    if not source_url:
        raise ValueError("a signal points at where it came from, or it is a rumour")

    correlation_id = correlation_id or audit.new_correlation_id()
    signal_id = conn.execute(
        """INSERT INTO actor_signal (actor_id, signal_kind, lga, locality,
                   observed_at, source_id, source_url, retrieved_at, detail,
                   evidence_id, origin)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (actor_id, signal_kind, lga, locality, observed_at, source_id,
         source_url, retrieved_at, detail.strip(), evidence_id, origin),
    ).fetchone()[0]

    audit.write(conn, correlation_id, "MARKET_SIGNAL_RECORDED", "actor_signal",
                signal_id, new_state={"signal_kind": signal_kind, "lga": lga,
                                      "locality": locality},
                actor_agent=ACTOR_AGENT)
    return signal_id


def hotspots(conn, *, lga: str | None = None, as_of: date | None = None,
             by_suburb: bool = True, include_demo: bool = False,
             limit: int = 25) -> list[Hotspot]:
    """Rank geographies by weighted, recency-decayed signal.

    Returns whole Hotspot objects rather than a bare number, because a ranking
    nobody can interrogate is a ranking nobody should act on: every score can be
    taken apart into the signals that produced it.
    """
    as_of = as_of or date.today()
    weights = active_weights(conn)

    where = ["1=1"]
    params: list = []
    if lga:
        where.append("s.lga ILIKE %s")
        params.append(lga)
    if not include_demo:
        where.append("s.origin = 'REAL'")

    rows = conn.execute(
        f"""SELECT s.lga, s.locality, s.signal_kind::text, s.observed_at,
                   s.detail, s.source_url, a.kind::text,
                   CASE WHEN a.publishable_by_name THEN a.name END
            FROM actor_signal s JOIN market_actor a ON a.id = s.actor_id
            WHERE {' AND '.join(where)}
            ORDER BY s.observed_at DESC""",
        params,
    ).fetchall()

    grouped: dict[tuple, Hotspot] = {}
    for row_lga, locality, kind, observed, detail, url, actor_kind, name in rows:
        key = (row_lga, locality if by_suburb else None)
        spot = grouped.setdefault(key, Hotspot(lga=key[0], locality=key[1],
                                               score=0.0, signal_count=0))
        age = as_of - observed
        recency = 1.0 if age < timedelta(0) else max(0.0, 1.0 - age / SIGNAL_HORIZON)
        contribution = Contribution(
            signal_kind=kind, weight=weights.get(kind, 0.0), recency=round(recency, 4),
            actor_name=name, actor_kind=actor_kind, detail=detail,
            source_url=url, observed_at=observed)
        spot.contributions.append(contribution)
        spot.score = round(spot.score + contribution.score, 4)
        spot.signal_count += 1

    ranked = sorted(grouped.values(), key=lambda h: -h.score)
    return ranked[:limit]


def government_intent(conn, *, lga: str | None = None, limit: int = 100):
    """Where government has flagged an intention to acquire.

    No new source: a Public Acquisition Overlay is a planning control used by a
    Minister, authority or council to identify land proposed to be acquired for
    a public purpose, and it is already in the overlay list on every parcel.
    """
    where = ["'PAO' = ANY(pc.overlay_codes)"]
    params: list = []
    if lga:
        where.append("p.lga ILIKE %s")
        params.append(lga)

    return conn.execute(
        f"""SELECT p.id, p.spi, p.lga, p.locality,
                   round((p.area_sqm / 4046.8564224)::numeric, 2) AS acres,
                   pc.zone_code, pc.overlay_codes, pc.psp_status, pc.as_at
            FROM parcel p JOIN parcel_planning_current pc ON pc.parcel_id = p.id
            WHERE {' AND '.join(where)}
            ORDER BY p.area_sqm DESC
            LIMIT %s""",
        params + [limit],
    ).fetchall()
