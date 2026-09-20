"""Land search: the query Crown actually asks.

    find land in Whittlesea between 20 and 150 acres, under investigation or
    draft, with or without a house, showing zoning and overlays

Every filter the prospecting brief listed is here. Four of them have no source
behind them yet — dwelling status, on-market, off-market and owner — and this
module is deliberate about the difference between "no" and "not known".

A parcel with no dwelling observation has UNKNOWN dwelling status, not False.
Filtering on a field nobody has data for returns nothing and says why, rather
than returning everything and implying the filter worked.
"""
from dataclasses import dataclass, field
from typing import Any

ACRE_SQM = 4046.8564224

# Planning status as the brief means it: what stage of change the land is under.
PLANNING_STATUSES = ("APPROVED", "DRAFT", "UNDER_INVESTIGATION", "NONE")

# Filters the brief specifies for which no source is registered yet. Asking for
# one is not an error — it is a question the data cannot answer, and the answer
# says so.
UNSOURCED_FILTERS = {
    "has_dwelling": "dwelling status has no registered source; see docs/PRODUCT-REVIEW.md",
    "on_market": "on-market status requires a portal feed agreement, not a crawler",
    "off_market": "off-market is a fact about a relationship; the source is CROWN_INBOX",
    "owner": "owner identification is Gate 0 — licensed and privacy-bound",
}


@dataclass
class LandQuery:
    lga: str | None = None
    locality: str | None = None
    min_acres: float | None = None
    max_acres: float | None = None
    zone_codes: list[str] = field(default_factory=list)
    any_overlay: list[str] = field(default_factory=list)
    exclude_overlay: list[str] = field(default_factory=list)
    planning_status: list[str] = field(default_factory=list)
    has_dwelling: bool | None = None
    include_crown_land: bool = False
    include_demo: bool = False
    limit: int = 200


@dataclass
class LandResult:
    parcel_id: str
    spi: str
    lga: str
    locality: str | None
    acres: float
    is_crown_land: bool | None
    zone_code: str | None
    zone_name: str | None
    overlays: list[str]
    psp_name: str | None
    psp_status: str | None
    planning_as_at: Any
    dwelling: str                # YES / NO / UNKNOWN — never a bare False
    amendments_touching: int
    origin: str

    @property
    def address(self) -> str:
        """The nearest thing to an address the open cadastre gives.

        Vicmap Property identifies a parcel by its standard parcel identifier.
        A street address comes from the address layer or from the Titles
        Register, so until one of those is registered this is what is honest.
        """
        parts = [self.spi]
        if self.locality:
            parts.append(self.locality)
        parts.append(self.lga)
        return ", ".join(parts)


@dataclass
class LandSearch:
    results: list[LandResult]
    total_matched: int
    unanswerable: dict           # filters asked for with no source behind them
    sql_explained: str           # what the query actually did, in words

    @property
    def is_empty_because_no_data(self) -> bool:
        return not self.results and self.total_matched == 0


def search(conn, query: LandQuery) -> LandSearch:
    """Run the land search. Reads only."""
    where = []
    params: list[Any] = []
    explained = []

    if query.lga:
        where.append("p.lga ILIKE %s")
        params.append(query.lga)
        explained.append(f"in {query.lga}")
    if query.locality:
        where.append("p.locality ILIKE %s")
        params.append(query.locality)
        explained.append(f"suburb {query.locality}")
    if query.min_acres is not None:
        where.append("p.area_sqm >= %s")
        params.append(query.min_acres * ACRE_SQM)
    if query.max_acres is not None:
        where.append("p.area_sqm <= %s")
        params.append(query.max_acres * ACRE_SQM)
    if query.min_acres is not None or query.max_acres is not None:
        explained.append(
            f"between {query.min_acres or 0:g} and "
            f"{query.max_acres if query.max_acres is not None else float('inf'):g} acres")
    if not query.include_crown_land:
        where.append("(p.is_crown_land IS NOT TRUE)")
        explained.append("freehold only")
    if not query.include_demo:
        where.append("p.origin = 'REAL'")

    if query.zone_codes:
        where.append("pc.zone_code = ANY(%s)")
        params.append(query.zone_codes)
        explained.append(f"zoned {', '.join(query.zone_codes)}")
    if query.any_overlay:
        where.append("pc.overlay_codes && %s")
        params.append(query.any_overlay)
        explained.append(f"with any of overlays {', '.join(query.any_overlay)}")
    if query.exclude_overlay:
        where.append("NOT (pc.overlay_codes && %s)")
        params.append(query.exclude_overlay)
        explained.append(f"without overlays {', '.join(query.exclude_overlay)}")
    if query.planning_status:
        where.append("pc.psp_status = ANY(%s)")
        params.append(query.planning_status)
        explained.append(f"planning status {', '.join(query.planning_status)}")

    unanswerable = {}
    if query.has_dwelling is not None:
        # Honoured where an observation exists, and reported as incomplete,
        # because most parcels will have none.
        where.append("pd.has_dwelling = %s")
        params.append(query.has_dwelling)
        unanswerable["has_dwelling"] = UNSOURCED_FILTERS["has_dwelling"]
        explained.append("with a dwelling" if query.has_dwelling else "without a dwelling")

    clause = (" WHERE " + " AND ".join(where)) if where else ""

    sql = f"""
        SELECT p.id, p.spi, p.lga, p.locality, p.area_sqm, p.is_crown_land,
               pc.zone_code, pc.zone_name, coalesce(pc.overlay_codes, '{{}}'),
               pc.psp_name, pc.psp_status, pc.as_at,
               CASE WHEN pd.has_dwelling IS TRUE THEN 'YES'
                    WHEN pd.has_dwelling IS FALSE THEN 'NO'
                    ELSE 'UNKNOWN' END,
               (SELECT count(*) FROM evidence_record e
                 WHERE e.lga = p.lga
                   AND (p.locality IS NULL
                        OR e.geography -> 'suburbs' ? p.locality)),
               p.origin::text
        FROM parcel p
        LEFT JOIN parcel_planning_current pc ON pc.parcel_id = p.id
        LEFT JOIN parcel_dwelling_current pd ON pd.parcel_id = p.id
        {clause}
        ORDER BY p.area_sqm DESC
        LIMIT %s
    """
    rows = conn.execute(sql, params + [query.limit]).fetchall()

    total = conn.execute(
        f"""SELECT count(*) FROM parcel p
            LEFT JOIN parcel_planning_current pc ON pc.parcel_id = p.id
            LEFT JOIN parcel_dwelling_current pd ON pd.parcel_id = p.id
            {clause}""",
        params,
    ).fetchone()[0]

    results = [
        LandResult(
            parcel_id=str(row[0]), spi=row[1], lga=row[2], locality=row[3],
            acres=round(float(row[4]) / ACRE_SQM, 2), is_crown_land=row[5],
            zone_code=row[6], zone_name=row[7], overlays=list(row[8]),
            psp_name=row[9], psp_status=row[10], planning_as_at=row[11],
            dwelling=row[12], amendments_touching=row[13], origin=row[14],
        )
        for row in rows
    ]

    return LandSearch(results=results, total_matched=total,
                      unanswerable=unanswerable,
                      sql_explained="parcels " + ", ".join(explained)
                      if explained else "every parcel")


def nearby(conn, parcel_id, radius_metres: int = 2000, limit: int = 50):
    """Parcels near this one.

    Centroid distance, not adjacency. Two parcels that share a boundary are
    near each other by this measure, but so is a parcel across the road, and a
    very large parcel's centroid can be far from its edge. True adjacency needs
    PostGIS; this is honest about being a proxy.
    """
    return conn.execute(
        """
        SELECT other.id, other.spi, other.locality,
               round((other.area_sqm / %s)::numeric, 2) AS acres,
               round(earth_distance(ll_to_earth(mine.centroid_lat, mine.centroid_lon),
                                    ll_to_earth(other.centroid_lat, other.centroid_lon))::numeric)
                 AS metres_between_centroids,
               pc.zone_code, coalesce(pc.overlay_codes, '{}'), pc.psp_status
        FROM parcel mine
        JOIN parcel other
          ON other.id <> mine.id
         AND other.centroid_lat IS NOT NULL
         AND earth_box(ll_to_earth(mine.centroid_lat, mine.centroid_lon), %s)
             @> ll_to_earth(other.centroid_lat, other.centroid_lon)
        LEFT JOIN parcel_planning_current pc ON pc.parcel_id = other.id
        WHERE mine.id = %s AND mine.centroid_lat IS NOT NULL
        ORDER BY metres_between_centroids
        LIMIT %s
        """,
        (ACRE_SQM, radius_metres, parcel_id, limit),
    ).fetchall()
