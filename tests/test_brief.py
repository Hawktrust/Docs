"""The Investment Committee brief — the page the whole pipeline exists to produce."""
import pytest

from crown import brief, recommendation
from tests.conftest import sign_in, user_id
from tests.test_prospecting_controls import approved


def a_recommendation(db, **kwargs):
    _, approval_id = approved(db, reference=kwargs.pop("reference", "TEST-BRIEF-1"))
    defaults = dict(decision="ACQUIRE", strategy="planning uplift",
                    timing="ONE_TO_THREE_YEARS",
                    rationale="gazetted rezoning in the precinct",
                    created_by=user_id(db, "analyst@crown.local"))
    defaults.update(kwargs)
    return recommendation.create(db, approval_id=approval_id, **defaults)


def test_the_brief_assembles_from_records_that_already_exist(db):
    b = brief.build(db, a_recommendation(db))
    assert b.decision == "ACQUIRE"
    assert b.confidence == "CONFIRMED"
    assert b.opportunity["lga"] == "Whittlesea" or b.opportunity["lga"]
    assert b.investment_case.body == "gazetted rezoning in the precinct"
    assert b.approval["by"] == "Crown Compliance"
    assert b.next_action


def test_it_shows_the_evidence_as_it_was_not_as_it_is(db):
    """The question a brief has to survive is: what did we know when we
    recommended this?"""
    rec_id = a_recommendation(db, reference="TEST-BRIEF-SNAP")
    before = brief.build(db, rec_id)
    assert before.evidence[0]["reference"] == "TEST-BRIEF-SNAP"

    db.execute("UPDATE evidence_record SET title = 'changed afterwards', "
               "amendment_status = 'SUPERSEDED'")
    after = brief.build(db, rec_id)
    assert after.evidence == before.evidence


def test_no_price_ceiling_without_the_assumptions_that_produced_it(db):
    b = brief.build(db, a_recommendation(db))
    assert not b.has_economics
    assert "Not computed" in b.price_ceiling.body
    assert b.price_ceiling.points == []


def test_economics_appear_beside_their_assumptions(db):
    rec_id = a_recommendation(
        db,
        economics={"residual_land_value_aud": 14_500_000, "price_ceiling_aud": 12_800_000},
        economics_assumptions={"net_developable_ha": 38, "lots_per_ha": 11,
                               "revenue_per_lot_aud": 385_000,
                               "infrastructure_contribution_per_lot_aud": 92_000,
                               "target_margin": 0.22})
    b = brief.build(db, rec_id)
    assert b.has_economics
    assert "estimate" in b.price_ceiling.body
    joined = " ".join(b.price_ceiling.points)
    assert "residual land value" in joined
    assert "— assumptions —" in b.price_ceiling.points
    assert "revenue per lot" in joined


def test_the_downside_names_the_risk_each_overlay_carries(db):
    """A brief should not hand a reader an overlay code to look up."""
    from tests.test_land_search import a_parcel

    rec_id = a_recommendation(db, reference="TEST-BRIEF-RISK")
    opportunity_id = db.execute("SELECT id FROM opportunity LIMIT 1").fetchone()[0]
    parcel_id = a_parcel(db, spi="TEST\\BRIEF1", overlays=("PAO", "BMO", "LSIO"),
                         origin="REAL")
    db.execute("INSERT INTO opportunity_parcel (opportunity_id, parcel_id) VALUES (%s,%s)",
               (opportunity_id, parcel_id))

    b = brief.build(db, rec_id)
    codes = {r["code"] for r in b.risks}
    assert codes == {"PAO", "BMO", "LSIO"}
    joined = " ".join(b.downside_case.points)
    assert "public acquisition" in joined
    assert "bushfire" in joined
    assert "inundation" in joined


def test_an_unknown_overlay_says_so_rather_than_inventing_a_risk(db):
    from tests.test_land_search import a_parcel

    rec_id = a_recommendation(db, reference="TEST-BRIEF-UNK")
    opportunity_id = db.execute("SELECT id FROM opportunity LIMIT 1").fetchone()[0]
    parcel_id = a_parcel(db, spi="TEST\\BRIEF2", overlays=("ZZO9",), origin="REAL")
    db.execute("INSERT INTO opportunity_parcel (opportunity_id, parcel_id) VALUES (%s,%s)",
               (opportunity_id, parcel_id))

    b = brief.build(db, rec_id)
    assert "no standard risk recorded" in b.risks[0]["risk"]


def test_a_numbered_overlay_still_resolves_its_risk(db):
    """DPO2 is a DPO. The schedule number does not change what the control is."""
    from tests.test_land_search import a_parcel

    rec_id = a_recommendation(db, reference="TEST-BRIEF-NUM")
    opportunity_id = db.execute("SELECT id FROM opportunity LIMIT 1").fetchone()[0]
    parcel_id = a_parcel(db, spi="TEST\\BRIEF3", overlays=("DPO2", "DCPO3"),
                         origin="REAL")
    db.execute("INSERT INTO opportunity_parcel (opportunity_id, parcel_id) VALUES (%s,%s)",
               (opportunity_id, parcel_id))

    joined = " ".join(r["risk"] for r in brief.build(db, rec_id).risks)
    assert "development plan" in joined
    assert "contributions" in joined


def test_a_weak_confidence_appears_in_the_downside(db):
    from tests.test_prospecting_controls import approved as make

    _, approval_id = make(db, reference="TEST-BRIEF-WEAK",
                          evidence_class="HYPOTHESIS",
                          retrieval_method="OPERATOR_CAPTURE")
    rec_id = recommendation.create(
        db, approval_id=approval_id, decision="WATCH", strategy="monitor",
        timing="LONG_TERM", rationale="early",
        created_by=user_id(db, "analyst@crown.local"))

    b = brief.build(db, rec_id)
    assert b.confidence == "SPECULATIVE"
    assert any("confidence is SPECULATIVE" in p for p in b.downside_case.points)


def test_no_linked_parcel_is_itself_reported_as_a_downside(db):
    b = brief.build(db, a_recommendation(db, reference="TEST-BRIEF-NOPARCEL"))
    assert any("no parcel has been linked" in p.lower()
               for p in b.downside_case.points)


def test_the_brief_renders(client, db):
    rec_id = a_recommendation(db, reference="TEST-BRIEF-PAGE")
    db.commit()
    sign_in(client, "analyst@crown.local")
    page = client.get(f"/brief/{rec_id}").get_data(as_text=True)

    assert "Investment Committee brief" in page
    assert "ACQUIRE" in page
    assert "Downside case" in page
    assert "Not computed" in page
    assert "TEST-BRIEF-PAGE" in page
    assert "Nothing in this brief leaves without it" in page


def test_a_missing_recommendation_is_a_404(client, db):
    db.commit()
    sign_in(client, "analyst@crown.local")
    assert client.get("/brief/00000000-0000-0000-0000-000000000000").status_code == 404


# ----------------------------------- what a brief may and may not carry

def test_a_brief_carries_no_landholder_identity(db):
    """The collection notice tells a landholder that Crown does not pass their
    name to a buyer. That sentence is only true while this stays true, so it is
    a test rather than an intention.

    If a landholder identity is ever added to what a brief carries, this fails
    — and section B of docs/compliance/COLLECTION-NOTICE.draft.md has to change
    before it can be made to pass, because handing a named landholder to a
    buyer is a disclosure to a third party.
    """
    from crown import approval, outbound
    from tests.test_governance import a_match

    _, match_id = a_match(db)
    approver = user_id(db, "compliance@crown.local")
    approval_id = approval.decide(db, match_id, "APPROVED", "checked",
                                  approver, "COMPLIANCE")

    content = outbound.build_content(db, approval_id, note="for the buyer")

    assert set(content) == {"note", "body", "approval", "opportunity",
                            "buyer", "score", "evidence"}
    # The land, the reasoning and the provenance. Not a person.
    assert set(content["opportunity"]) == {"lga", "geography", "stage",
                                           "stage_rule"}
    assert set(content["buyer"]) == {"label", "origin"}
    for item in content["evidence"]:
        assert "landholder" not in item
        assert "owner" not in item
