"""The loop as a person walks it: opportunity -> ranking -> queue -> decision."""
from crown import matching, opportunity
from tests.conftest import add_evidence, csrf, sign_in, user_id


def an_opportunity(db):
    add_evidence(db, reference="TEST-C070wynd")
    owner = user_id(db, "analyst@crown.local")
    oid = opportunity.refresh(db, owner)[0].opportunity_id
    db.commit()
    return oid


def test_viewing_a_ranking_does_not_write_one(client, db):
    """A GET must not change the database. The ranking is shown, not stored."""
    oid = an_opportunity(db)
    sign_in(client, "analyst@crown.local")

    page = client.get(f"/opportunities/{oid}")
    assert page.status_code == 200
    assert db.execute("SELECT count(*) FROM match_result").fetchone()[0] == 0


def test_recomputing_stores_the_ranking_and_fills_the_queue(client, db):
    oid = an_opportunity(db)
    sign_in(client, "analyst@crown.local")

    assert client.get("/queue").get_data(as_text=True).count("Queue is empty") == 1

    response = client.post(f"/opportunities/{oid}/rematch", data=csrf(client))
    assert response.status_code == 302
    assert db.execute("SELECT count(*) FROM match_result").fetchone()[0] == 20

    queue = client.get("/queue").get_data(as_text=True)
    assert "Queue is empty" not in queue


def test_an_agent_may_not_recompute_a_ranking(client, db):
    oid = an_opportunity(db)
    sign_in(client, "agent@crown.local")
    assert client.post(f"/opportunities/{oid}/rematch",
                       data=csrf(client)).status_code == 403
    assert db.execute("SELECT count(*) FROM match_result").fetchone()[0] == 0


def test_the_stage_rule_is_displayed_not_only_coded(client, db):
    """Ticket item 3: the rule is readable in the code and displayed in the UI."""
    an_opportunity(db)
    sign_in(client, "analyst@crown.local")
    page = client.get("/opportunities").get_data(as_text=True)
    assert "CONFIRMED" in page
    assert "gazetted" in page                      # the reason this one is CONFIRMED
    assert "Stage rule:" in page                   # and the rule in general
    assert opportunity.RULE_DESCRIPTION[:40] in page


def test_the_evidence_pack_is_shown_before_a_decision(client, db):
    """Ticket item 6: a named human opens a match and sees the evidence pack."""
    oid = an_opportunity(db)
    sign_in(client, "compliance@crown.local")
    matching.rank(db, oid)
    db.commit()
    match_id = db.execute(
        "SELECT id FROM match_result WHERE NOT is_excluded LIMIT 1").fetchone()[0]

    page = client.get(f"/queue/{match_id}").get_data(as_text=True)
    assert "Evidence pack" in page
    assert "TEST-C070wynd" in page
    assert "https://www.planning.vic.gov.au/amendment/TEST-C070wynd" in page
    assert "AUTHORITATIVE" in page
    assert 'name="reason"' in page                 # a decision needs a reason


def test_an_analyst_sees_the_pack_but_gets_no_decision_form(client, db):
    oid = an_opportunity(db)
    matching.rank(db, oid)
    db.commit()
    match_id = db.execute(
        "SELECT id FROM match_result WHERE NOT is_excluded LIMIT 1").fetchone()[0]

    sign_in(client, "analyst@crown.local")
    page = client.get(f"/queue/{match_id}").get_data(as_text=True)
    assert "Evidence pack" in page
    assert 'name="decision"' not in page
    assert "may not decide approvals" in page


def test_approving_writes_the_attribution_in_the_same_step(client, db):
    """Ticket item 7: when an approved match progresses, attribution is written."""
    oid = an_opportunity(db)
    matching.rank(db, oid)
    db.commit()
    match_id = db.execute(
        "SELECT id FROM match_result WHERE NOT is_excluded ORDER BY total_score DESC LIMIT 1"
    ).fetchone()[0]

    sign_in(client, "compliance@crown.local")
    response = client.post(f"/queue/{match_id}/decide",
                           data={"decision": "APPROVED", "reason": "pack checked",
                                 **csrf(client)})
    assert response.status_code == 302

    row = db.execute(
        """SELECT a.originating_source_url, a.originating_retrieved_at
           FROM attribution a""").fetchone()
    assert row is not None
    assert row[0] == "https://www.planning.vic.gov.au/amendment/TEST-C070wynd"
    assert row[1] is not None


def test_a_decision_without_a_reason_is_refused(client, db):
    oid = an_opportunity(db)
    matching.rank(db, oid)
    db.commit()
    match_id = db.execute(
        "SELECT id FROM match_result WHERE NOT is_excluded LIMIT 1").fetchone()[0]

    sign_in(client, "compliance@crown.local")
    client.post(f"/queue/{match_id}/decide",
                data={"decision": "APPROVED", "reason": "  ", **csrf(client)})
    assert db.execute("SELECT count(*) FROM approval").fetchone()[0] == 0
