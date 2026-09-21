"""The Investment Committee brief.

One page per shortlisted opportunity: the investment case, the downside case,
the recommended price ceiling, the next action and the evidence links.

Everything here is assembled from records that already exist. The brief invents
nothing — it is a view over the recommendation, its frozen evidence snapshot,
the land, the market signals and the risks the overlays imply. If a section has
no basis, it says so rather than filling the space.

Two things it refuses to do.

It does not show a price ceiling without the assumptions that produced it. A
residual land value moves enormously on a small change to a sales rate, and a
number printed beside provenanced planning evidence borrows a credibility it has
not earned.

It does not show evidence as it is now. It shows the snapshot taken when the
recommendation was made, because the question a brief has to survive is "what
did we know when we recommended this?"
"""
from dataclasses import dataclass, field

# Overlays that carry a named risk, and what the risk is. Stated here so a brief
# never presents an overlay code to a reader who has to look it up.
OVERLAY_RISKS = {
    "PAO": "public acquisition — an authority has flagged intent to acquire; "
           "timing is not yours and compensation is at market value",
    "BMO": "bushfire management — construction standards and defendable space "
           "obligations",
    "LSIO": "land subject to inundation — flood constraints on developable area",
    "SBO": "special building — flood-related construction controls",
    "EAO": "environmental audit — potential contamination; an audit may be "
           "required before sensitive use",
    "HO": "heritage — demolition and works controls",
    "ESO": "environmental significance — vegetation and siting controls",
    "VPO": "vegetation protection — removal controls",
    "SLO": "significant landscape — siting and design controls",
    "DCPO": "development contributions — levies payable on development",
    "DPO": "development plan — an approved plan is required before permits",
    "IPO": "incorporated plan — an approved plan is required before permits",
}


@dataclass
class Section:
    heading: str
    body: str
    points: list = field(default_factory=list)


@dataclass
class Brief:
    recommendation_id: str
    opportunity: dict
    decision: str
    strategy: str
    timing: str
    confidence: str
    principal: str
    rationale: str
    investment_case: Section
    downside_case: Section
    price_ceiling: Section
    next_action: str
    evidence: list
    risks: list
    signals: list
    approval: dict

    @property
    def has_economics(self) -> bool:
        return bool(self.price_ceiling.points)


def _overlay_risks(overlays) -> list:
    risks = []
    for code in overlays or []:
        base = code.rstrip("0123456789")
        explanation = OVERLAY_RISKS.get(code) or OVERLAY_RISKS.get(base)
        risks.append({"code": code,
                      "risk": explanation or "no standard risk recorded for this "
                                             "overlay; read the schedule"})
    return risks


def build(conn, recommendation_id) -> Brief:
    row = conn.execute(
        """SELECT r.decision::text, r.strategy, r.timing::text, r.confidence::text,
                  r.principal::text, r.principal_label, r.rationale,
                  r.economics, r.economics_assumptions, r.evidence_snapshot,
                  o.id, o.lga, o.geography_label, o.stage::text, o.stage_rule,
                  o.next_action, u.display_name,
                  a.id, a.decision::text, a.reason, a.decided_at, au.display_name
           FROM recommendation r
           JOIN opportunity o ON o.id = r.opportunity_id
           JOIN app_user u    ON u.id = r.created_by
           JOIN approval a    ON a.id = r.approval_id
           JOIN app_user au   ON au.id = a.approver_id
           WHERE r.id = %s""",
        (recommendation_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"no recommendation {recommendation_id}")

    (decision, strategy, timing, confidence, principal, principal_label, rationale,
     economics, assumptions, snapshot, opportunity_id, lga, geography, stage,
     stage_rule, next_action, author, approval_id, approval_decision,
     approval_reason, decided_at, approver) = row

    # Land under the opportunity, where any has been linked.
    parcels = conn.execute(
        """SELECT p.spi, round((p.area_sqm / 4046.8564224)::numeric, 2),
                  pc.zone_code, coalesce(pc.overlay_codes, '{}'), pc.psp_status
           FROM opportunity_parcel op
           JOIN parcel p ON p.id = op.parcel_id
           LEFT JOIN parcel_planning_current pc ON pc.parcel_id = p.id
           WHERE op.opportunity_id = %s
           ORDER BY p.area_sqm DESC""",
        (opportunity_id,),
    ).fetchall()

    # Market activity in the same geography, named where naming is allowed.
    market = conn.execute(
        """SELECT s.signal_kind::text, s.detail, s.source_url, s.observed_at,
                  CASE WHEN a.publishable_by_name THEN a.name END, a.kind::text
           FROM actor_signal s JOIN market_actor a ON a.id = s.actor_id
           WHERE s.lga = %s AND (s.locality = %s OR s.locality IS NULL)
             AND s.origin = 'REAL'
           ORDER BY s.observed_at DESC LIMIT 10""",
        (lga, geography),
    ).fetchall()

    evidence = (snapshot or {}).get("evidence", [])

    # --- the case
    case_points = [f"{stage}: {stage_rule}"]
    for line in evidence[:4]:
        case_points.append(
            f"{line['reference']} — {line['class'].lower()}, "
            f"{line['retrieval_method'].replace('_', ' ').lower()}, "
            f"observed {line['observed_at'][:10]}")
    for kind, detail, _, observed, name, actor_kind in market[:3]:
        who = name or f"an unnamed {actor_kind.replace('_', ' ').lower()}"
        case_points.append(f"{observed}: {who} — {detail}")

    investment_case = Section(
        heading="Investment case",
        body=rationale,
        points=case_points)

    # --- the downside
    all_overlays = sorted({code for _, _, _, overlays, _ in parcels
                           for code in (overlays or [])})
    risks = _overlay_risks(all_overlays)

    downside_points = [r["code"] + " — " + r["risk"] for r in risks]
    if confidence != "CONFIRMED":
        downside_points.append(
            f"confidence is {confidence}: the evidence under this has not been "
            "directly verified by the system, so the case rests on a weaker read "
            "than it appears to")
    if not evidence:
        downside_points.append(
            "no evidence was linked when this was recommended, which is the "
            "largest downside on this page")
    if not parcels:
        downside_points.append(
            "no parcel has been linked, so acreage, zoning and overlay risk are "
            "not assessed for this opportunity")

    downside_case = Section(
        heading="Downside case",
        body="What would have to be true for this to be a mistake." if downside_points
             else "No downside has been recorded, which is itself a finding.",
        points=downside_points)

    # --- the ceiling
    if economics and assumptions:
        ceiling = Section(
            heading="Recommended price ceiling",
            body="Every figure below is an estimate. The assumptions that produced "
                 "it are listed beside it, and changing any of them moves the "
                 "answer materially.",
            points=[f"{k.replace('_', ' ')}: {v}" for k, v in economics.items()]
                   + ["— assumptions —"]
                   + [f"{k.replace('_', ' ')}: {v}" for k, v in assumptions.items()])
    else:
        ceiling = Section(
            heading="Recommended price ceiling",
            body="Not computed. Economics are only shown with the assumptions that "
                 "produced them, and none were recorded for this recommendation.",
            points=[])

    return Brief(
        recommendation_id=str(recommendation_id),
        opportunity={"id": str(opportunity_id), "lga": lga, "geography": geography,
                     "stage": stage, "stage_rule": stage_rule, "author": author,
                     "parcels": [{"spi": s, "acres": float(a),
                                  "zone": z, "overlays": list(o or []),
                                  "psp_status": p}
                                 for s, a, z, o, p in parcels]},
        decision=decision, strategy=strategy, timing=timing, confidence=confidence,
        principal=f"{principal_label} ({principal.replace('_', ' ').lower()})",
        rationale=rationale,
        investment_case=investment_case, downside_case=downside_case,
        price_ceiling=ceiling,
        next_action=next_action or "not set",
        evidence=evidence,
        risks=risks,
        signals=[{"kind": k, "detail": d, "url": u, "observed_at": str(o),
                  "actor": n or f"unnamed {ak.replace('_', ' ').lower()}"}
                 for k, d, u, o, n, ak in market],
        approval={"id": str(approval_id), "decision": approval_decision,
                  "reason": approval_reason, "by": approver,
                  "at": decided_at.isoformat()},
    )
