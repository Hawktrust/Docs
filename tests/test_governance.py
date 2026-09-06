"""Controls an auditor asks for, and the numbers a CEO is shown.

Each test below corresponds to a question the system could not answer before
migration 0005 and crown/reports.py.
"""
import psycopg
import pytest

from crown import approval, matching, opportunity, outbound, reports
from tests.conftest import add_evidence, csrf, sign_in, user_id


def a_match(db):
    add_evidence(db, reference="TEST-GOV-1")
    owner = user_id(db, "analyst@crown.local")
    oid = opportunity.refresh(db, owner)[0].opportunity_id
    matching.rank(db, oid)
    return oid, db.execute(
        """SELECT id FROM match_result WHERE NOT is_excluded
           ORDER BY total_score DESC LIMIT 1""").fetchone()[0]


# ---------------------------------------------- "who did this?" must be answerable

def test_an_audit_row_cannot_be_attributed_to_nobody(db):
    with pytest.raises(psycopg.errors.CheckViolation, match="audit_event_has_an_actor"):
        db.execute(
            """INSERT INTO audit_event (action, object_table, object_id, correlation_id)
               VALUES ('ORPHAN','app_user','x', gen_random_uuid())""")
    db.rollback()


def test_signing_in_and_out_is_recorded(client, db):
    db.commit()
    sign_in(client, "analyst@crown.local")
    client.post("/logout", data=csrf(client))

    actions = [r[0] for r in db.execute(
        "SELECT action FROM audit_event WHERE actor_agent = 'crown.web' ORDER BY id"
    ).fetchall()]
    assert "SIGN_IN" in actions and "SIGN_OUT" in actions


def test_a_failed_sign_in_is_recorded(client, db):
    db.commit()
    response = client.post("/login", data={"email": "nobody@crown.local"})
    assert response.status_code == 401

    row = db.execute(
        """SELECT object_id, new_state FROM audit_event
           WHERE action = 'SIGN_IN_FAILED'""").fetchone()
    assert row[0] == "nobody@crown.local"


def test_a_refused_action_is_recorded(client, db):
    """The attempts that fail are the ones an auditor most wants to see."""
    oid, _ = a_match(db)
    db.commit()
    sign_in(client, "agent@crown.local")

    assert client.post(f"/opportunities/{oid}/rematch",
                       data=csrf(client)).status_code == 403

    row = db.execute(
        """SELECT new_state FROM audit_event WHERE action = 'AUTHORISATION_DENIED'"""
    ).fetchone()
    assert row is not None
    assert row[0]["role_held"] == "AGENT"
    assert "ANALYST" in row[0]["roles_required"]


# ------------------------------------- "who changed the numbers that pick the buyer?"

def test_changing_the_scoring_weights_is_recorded_whatever_writes_them(db):
    """AC6 makes these changeable without a deploy, so they must be accountable."""
    before = db.execute(
        "SELECT count(*) FROM audit_event WHERE object_table = 'match_weight_config'"
    ).fetchone()[0]

    db.execute("SELECT set_config('crown.user_id', %s, true)",
               (str(user_id(db, "hawk@crown.local")),))
    db.execute(
        """INSERT INTO match_weight_config (version, geographic_fit, asset_fit,
               price_fit, size_fit, mandate_freshness, is_active)
           VALUES (7, 0.900, 0.025, 0.025, 0.025, 0.025, false)""")

    rows = db.execute(
        """SELECT action, actor_user_id, new_state FROM audit_event
           WHERE object_table = 'match_weight_config' ORDER BY id DESC LIMIT 1"""
    ).fetchone()
    assert db.execute(
        "SELECT count(*) FROM audit_event WHERE object_table = 'match_weight_config'"
    ).fetchone()[0] == before + 1
    assert rows[0] == "SCORING_WEIGHTS_INSERT"
    assert rows[1] is not None, "the change is attributed to the user who made it"
    assert float(rows[2]["geographic_fit"]) == 0.9


def test_activating_a_different_weight_set_is_recorded_with_what_it_replaced(db):
    db.execute("UPDATE match_weight_config SET is_active = false WHERE version = 1")
    row = db.execute(
        """SELECT action, previous_state, new_state FROM audit_event
           WHERE object_table = 'match_weight_config' ORDER BY id DESC LIMIT 1"""
    ).fetchone()
    assert row[0] == "SCORING_WEIGHTS_UPDATE"
    assert row[1]["is_active"] is True and row[2]["is_active"] is False


# ------------------------------------------------- segregation of duties

def test_a_person_cannot_approve_their_own_opportunity(db):
    """'Nothing leaves without approval' means little if the author approves it."""
    _, match_id = a_match(db)
    owner = user_id(db, "analyst@crown.local")      # who raised the opportunity

    with pytest.raises(psycopg.errors.RaiseException, match="cannot approve its own"):
        db.execute(
            """INSERT INTO approval (match_result_id, decision, reason, approver_id)
               VALUES (%s,'APPROVED','approving my own work',%s)""", (match_id, owner))
    db.rollback()


def test_a_second_named_human_can(db):
    _, match_id = a_match(db)
    approver = user_id(db, "compliance@crown.local")
    approval.decide(db, match_id, "APPROVED", "reviewed", approver, "COMPLIANCE")
    assert db.execute("SELECT count(*) FROM approval").fetchone()[0] == 1


# --------------------------------------------------- data rights exceptions

def test_ingesting_without_a_signed_register_entry_is_reported(db):
    """The register says register_confirmed_by is NULL until a named adviser
    signs. The one ingestible source has been ingestible with it empty."""
    exceptions = reports.data_rights_exceptions(db)
    codes = {row[0] for row in exceptions}
    assert "VIC_PLANNING_AMENDMENTS" in codes
    assert any("no named adviser has confirmed" in row[4] for row in exceptions)


def test_signing_the_register_clears_the_exception(db):
    db.execute(
        """UPDATE data_source SET register_confirmed_by = 'A. Named Adviser',
               register_confirmed_at = now()
           WHERE code = 'VIC_PLANNING_AMENDMENTS'""")
    assert reports.data_rights_exceptions(db) == []


def test_a_blocked_source_is_not_an_exception(db):
    """RP_DATA_SEAT has no licence either, but it is not being ingested."""
    codes = {row[0] for row in reports.data_rights_exceptions(db)}
    assert "RP_DATA_SEAT" not in codes


# ------------------------------------------------------------- the numbers

def test_the_overview_counts_only_real_records(db):
    add_evidence(db, reference="TEST-GOV-2", origin="DEMO_SYNTHETIC")
    db.execute(
        """INSERT INTO buyer_mandate (buyer_label, origin, geographies, asset_types,
               mandate_date)
           VALUES ('a real mandate','REAL','{Wyndham}','{RESIDENTIAL_LAND}','2026-08-01')""")

    o = reports.overview(db)
    assert o.real_evidence == 0          # the fixture above is demo
    assert o.demo_evidence == 1
    assert o.real_mandates == 1          # the twenty seeded ones are synthetic
    assert o.synthetic_mandates == 20
    assert o.data_rights_exceptions == 1


def test_the_overview_says_plainly_when_there_is_no_real_evidence(client, db):
    db.commit()
    sign_in(client, "analyst@crown.local")
    page = client.get("/overview").get_data(as_text=True)
    assert "No real evidence has been ingested" in page


def test_only_compliance_and_admin_see_the_compliance_page(client, db):
    db.commit()
    sign_in(client, "agent@crown.local")
    assert client.get("/compliance").status_code == 403

    sign_in(client, "compliance@crown.local")
    page = client.get("/compliance")
    assert page.status_code == 200
    assert "Data rights exceptions" in page.get_data(as_text=True)


# ------------------------------------------------- what actually goes out

def test_an_outbound_artifact_carries_the_chain_that_justifies_it(db):
    """A gated export that says nothing is gated and useless."""
    _, match_id = a_match(db)
    approver = user_id(db, "compliance@crown.local")
    approval_id = approval.decide(db, match_id, "APPROVED", "pack checked",
                                  approver, "COMPLIANCE")

    content = outbound.build_content(db, approval_id, note="for the buyer")
    outbound.create(db, approval_id, "BUYER_BRIEF", content, approver)

    stored = db.execute(
        "SELECT content FROM outbound_artifact").fetchone()[0]
    assert stored["approval"]["approved_by"] == "Crown Compliance"
    assert stored["approval"]["reason"] == "pack checked"
    assert stored["opportunity"]["stage_rule"]
    assert set(stored["score"]["contributions"]) == {
        "geographic_fit", "asset_fit", "price_fit", "size_fit", "mandate_freshness"}
    assert stored["evidence"][0]["reference"] == "TEST-GOV-1"
    assert stored["evidence"][0]["source_url"].startswith("https://")
    assert stored["evidence"][0]["retrieval_method"] == "DIRECT_FETCH"


def test_the_artifact_names_the_buyer_as_synthetic_when_it_is(db):
    _, match_id = a_match(db)
    approver = user_id(db, "compliance@crown.local")
    approval_id = approval.decide(db, match_id, "APPROVED", "ok", approver, "COMPLIANCE")
    content = outbound.build_content(db, approval_id)
    assert content["buyer"]["origin"] == "DEMO_SYNTHETIC"


# ------------------------------- demo data must not launder into real figures

def test_an_opportunity_built_from_demo_evidence_is_not_real(db):
    """The origin column exists to prevent this, and the rule engine ignored it:
    five demo evidence records produced four opportunities marked REAL, which
    were then counted in figures shown to a person."""
    add_evidence(db, reference="TEST-GOV-D1", origin="DEMO_SYNTHETIC")
    owner = user_id(db, "analyst@crown.local")

    change = opportunity.refresh(db, owner)[0]
    assert change.origin == "DEMO_SYNTHETIC"
    assert db.execute(
        "SELECT origin::text FROM opportunity").fetchone()[0] == "DEMO_SYNTHETIC"

    o = reports.overview(db)
    assert o.opportunities == 0
    assert o.demo_opportunities == 1


def test_one_real_evidence_record_makes_the_opportunity_real(db):
    add_evidence(db, reference="TEST-GOV-D2", origin="DEMO_SYNTHETIC", suburb="Tarneit")
    add_evidence(db, reference="TEST-GOV-D3", origin="REAL", suburb="Tarneit")
    owner = user_id(db, "analyst@crown.local")

    assert opportunity.refresh(db, owner)[0].origin == "REAL"
    assert reports.overview(db).opportunities == 1


def test_restaging_corrects_an_origin_that_has_changed(db):
    """A demo opportunity that later gains real evidence becomes real."""
    add_evidence(db, reference="TEST-GOV-D4", origin="DEMO_SYNTHETIC", suburb="Tarneit")
    owner = user_id(db, "analyst@crown.local")
    assert opportunity.refresh(db, owner)[0].origin == "DEMO_SYNTHETIC"

    add_evidence(db, reference="TEST-GOV-D5", origin="REAL", suburb="Tarneit")
    assert opportunity.refresh(db, owner)[0].origin == "REAL"
    assert db.execute("SELECT count(*) FROM opportunity").fetchone()[0] == 1


def test_a_match_is_real_only_if_both_sides_are(db):
    """Every seeded mandate is synthetic, so no match against them is real,
    however real the opportunity is."""
    add_evidence(db, reference="TEST-GOV-D6", origin="REAL")
    owner = user_id(db, "analyst@crown.local")
    oid = opportunity.refresh(db, owner)[0].opportunity_id
    matching.rank(db, oid)

    o = reports.overview(db)
    assert o.opportunities == 1
    assert o.matches_awaiting_decision == 0
    assert o.demo_matches_awaiting_decision > 0
