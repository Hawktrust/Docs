"""Nothing is kept forever.

The privacy policy states retention periods. Before 0026 nothing expired, so
the policy described an intention and a person reading it was told something
untrue about the system. A published period nobody implements is worse than an
admitted absence, because it is relied on.
"""
import psycopg
import pytest

from crown import outbound, retention
from tests.conftest import a_body, approved_match, user_id
from tests.test_optout import an_identity

POST = {"channel": "POST", "recipient_class": "LANDHOLDER_FROM_REGISTER"}


def an_actor(db, name="Some Developer Pty Ltd", age="13 months"):
    from crown.suppression import normalise
    return db.execute(
        f"""INSERT INTO market_actor (name, normalised, kind, created_at)
            VALUES (%s, %s, 'PRIVATE_DEVELOPER', now() - interval '{age}')
            RETURNING id""", (name, normalise(name))).fetchone()[0]


def age_artifact(db, artifact_id, age="8 years"):
    db.execute(f"""UPDATE outbound_artifact
                   SET created_at = now() - interval '{age}' WHERE id = %s""",
               (artifact_id,))


def a_message(db, to="A. Landholder"):
    an_identity(db)
    approval_id, creator = approved_match(db)
    return outbound.create(db, approval_id, "OUTREACH_DRAFT",
                           {"body": a_body()}, creator,
                           contact={"PERSON": to}, **POST)


# ------------------------------------------------------------- the periods

def test_the_periods_are_data_and_not_a_query(db):
    """In a table so that changing one is a recorded act with a reason, rather
    than an edit to a function nobody reviews."""
    by_category = {r[0]: r for r in retention.rules(db)}
    assert by_category["ACTOR_NEVER_APPROACHED"][1].days == 365
    assert by_category["ARTEFACT_RECIPIENT"][1].days == 2555     # 7 years
    assert by_category["SUPPRESSION"][1] is None
    assert by_category["AUDIT"][1] is None


def test_every_rule_says_why(db):
    """A period with no reason is one nobody can argue with, which means it is
    one nobody revisits."""
    for _, _, _, basis in retention.rules(db):
        assert len(basis) > 40


def test_the_policy_and_the_database_agree(db):
    """If these disagree, the privacy policy is promising something the system
    does not do — which is the failure this migration exists to end."""
    import pathlib
    policy = (pathlib.Path(__file__).resolve().parent.parent
              / "docs/compliance/PRIVACY-POLICY.draft.md").read_text()
    assert "12 months" in policy
    assert "7 years" in policy
    periods = {r[0]: r[1] for r in retention.rules(db)}
    assert periods["ACTOR_NEVER_APPROACHED"].days == 365
    assert periods["ARTEFACT_RECIPIENT"].days == 2555


# ------------------------------------------------------------ what is due

def test_a_fresh_actor_is_not_due(db):
    an_actor(db, age="1 month")
    assert retention.due(db) == []


def test_an_actor_never_approached_expires(db):
    an_actor(db)
    due = retention.due(db)
    assert [r[0] for r in due] == ["ACTOR_NEVER_APPROACHED"]


def test_an_actor_who_was_approached_does_not(db):
    """Once a name has been written to, the artefact period governs it. Two
    rules over one person, with the shorter winning, would delete the name
    while the message to them was still on record."""
    an_actor(db, name="A. Landholder")
    a_message(db, to="A. Landholder")
    assert retention.due(db) == []


def test_an_old_artefact_recipient_expires(db):
    artifact_id = a_message(db)
    age_artifact(db, artifact_id)
    due = retention.due(db)
    assert [r[0] for r in due] == ["ARTEFACT_RECIPIENT"]
    assert due[0][2] == str(artifact_id)


def test_a_recent_artefact_does_not(db):
    a_message(db)
    assert retention.due(db) == []


# ------------------------------------------------------------- the sweep

def test_a_dry_run_changes_nothing(db):
    an_actor(db)
    rows = retention.apply(db, dry_run=True)
    assert len(rows) == 1
    assert rows[0][3] is False
    assert db.execute("SELECT count(*) FROM market_actor").fetchone()[0] == 1


def test_applying_it_removes_the_actor(db):
    an_actor(db)
    retention.apply(db, dry_run=False)
    assert db.execute("SELECT count(*) FROM market_actor").fetchone()[0] == 0
    assert retention.due(db) == []


def test_the_person_goes_and_the_decision_stays(db):
    """The heart of it. APP 11.2 says stop holding the personal information;
    the audit trail says a decision taken stays visible. Deleting the artefact
    would satisfy the first and defeat the second, so the name is removed and
    the record of Crown's conduct is not."""
    artifact_id = a_message(db)
    age_artifact(db, artifact_id)
    retention.apply(db, dry_run=False)

    scope, identifier, approval_id, content = db.execute(
        """SELECT contact_scope, contact_identifier, approval_id, content
           FROM outbound_artifact WHERE id = %s""", (artifact_id,)).fetchone()

    # A tombstone, not a blank. 0018 requires a message to a person to name
    # its recipient; 0026 requires the name gone after seven years. Both are
    # right, at different times, and NULL would satisfy the second by breaking
    # the first. The tombstone is also more truthful: a blank reads as "nobody
    # was named" rather than "the name was removed on purpose".
    assert identifier == "[removed: retention period expired]"
    assert scope == "PERSON"             # that it went to a person is conduct
    assert approval_id is not None       # the decision stays
    assert content                       # and so does what was said


def test_every_removal_is_audited(db):
    an_actor(db)
    retention.apply(db, dry_run=False)
    rows = db.execute(
        """SELECT new_state FROM audit_event
           WHERE action = 'RETENTION_APPLIED'""").fetchall()
    assert len(rows) == 1
    assert rows[0][0]["category"] == "ACTOR_NEVER_APPROACHED"
    assert rows[0][0]["action"] == "deleted"


def test_a_dry_run_audits_nothing(db):
    """It did not happen, so it is not written down as having happened."""
    an_actor(db)
    retention.apply(db, dry_run=True)
    assert db.execute(
        """SELECT count(*) FROM audit_event
           WHERE action = 'RETENTION_APPLIED'""").fetchone()[0] == 0


def test_sweeping_twice_is_a_no_op(db):
    """A scheduler re-runs after a crash, and a cron entry can overlap itself."""
    an_actor(db)
    retention.apply(db, dry_run=False)
    assert retention.apply(db, dry_run=False) == []


# ------------------------------------------------- what is never expired

def test_a_suppression_outlives_everything(db):
    """The one place where keeping data is the privacy-protective choice: a
    request not to be contacted must outlive the data it protects, or the
    person is contacted again by a system that forgot."""
    from datetime import datetime, timezone
    from crown import suppression
    suppression.record(db, scope="PERSON", identifier="A. Landholder",
                       reason="asked to be left alone",
                       requested_at=datetime.now(timezone.utc),
                       recorded_by=user_id(db, "analyst@crown.local"),
                       source_of_request="EMAIL")
    db.execute("""UPDATE contact_suppression
                  SET created_at = now() - interval '20 years'""")

    retention.apply(db, dry_run=False)
    assert db.execute(
        "SELECT count(*) FROM contact_suppression").fetchone()[0] == 1


def test_the_audit_trail_is_never_swept(db):
    """It cannot even be aged to test this: audit_event refuses UPDATE, which
    is 0005 doing its job. So the assertion is the stronger one — no category
    in the rules touches it, and a sweep only ever adds rows to it."""
    categories = {r[2] for r in retention.rules(db)}
    assert not any(c.startswith("audit_event") and "period" in c
                   for c in categories)
    audit_rule = [r for r in retention.rules(db) if r[0] == "AUDIT"][0]
    assert audit_rule[1] is None                      # never expires

    an_actor(db)
    before = db.execute("SELECT count(*) FROM audit_event").fetchone()[0]
    retention.apply(db, dry_run=False)
    after = db.execute("SELECT count(*) FROM audit_event").fetchone()[0]
    assert after > before          # a sweep only ever adds to it


def test_an_old_account_is_not_swept(db):
    """Attribution of decisions already taken. Closing an account is a separate
    act from forgetting who made a decision."""
    db.execute("SELECT 1")
    before = db.execute("SELECT count(*) FROM app_user").fetchone()[0]
    retention.apply(db, dry_run=False)
    assert db.execute("SELECT count(*) FROM app_user").fetchone()[0] == before


# ------------------------------------------------------ the entry point

def test_the_scheduler_entry_point_defaults_to_a_dry_run(database, capsys):
    """A sweep that acts by default is one somebody runs by accident against
    the wrong database, and this one cannot be undone."""
    from scripts import retention as script
    owner_dsn, _ = database
    with psycopg.connect(owner_dsn) as conn:
        an_actor(conn)
        conn.commit()

    assert script.main(["--dsn", owner_dsn]) == 0
    assert "would remove" in capsys.readouterr().out

    with psycopg.connect(owner_dsn) as conn:
        row = conn.execute("SELECT count(*) FROM market_actor").fetchone()
    assert row is not None and row[0] == 1


def test_the_entry_point_acts_when_told(database, capsys):
    from scripts import retention as script
    owner_dsn, _ = database
    with psycopg.connect(owner_dsn) as conn:
        an_actor(conn)
        conn.commit()

    assert script.main(["--dsn", owner_dsn, "--apply"]) == 0
    assert "removed" in capsys.readouterr().out

    with psycopg.connect(owner_dsn) as conn:
        row = conn.execute("SELECT count(*) FROM market_actor").fetchone()
    assert row is not None and row[0] == 0


def test_a_quiet_run_with_nothing_due_says_nothing(database, capsys):
    from scripts import retention as script
    owner_dsn, _ = database
    assert script.main(["--dsn", owner_dsn, "--quiet"]) == 0
    assert capsys.readouterr().out == ""


def test_a_failed_run_says_so_where_a_scheduler_will_see_it(capsys):
    from scripts import retention as script
    assert script.main(["--dsn", "postgresql://nobody@127.0.0.1:1/nothing"]) == 1
    assert "retention run failed" in capsys.readouterr().err


def test_de_identifying_does_not_break_the_0018_constraint(db):
    """The collision this migration had to resolve. A message to a person must
    name its recipient (0018) and must stop naming them after seven years
    (0026). Nulling the column satisfies the second by breaking the first, and
    weakening 0018 to allow it would trade a live control for a dead one."""
    artifact_id = a_message(db)
    age_artifact(db, artifact_id)
    retention.apply(db, dry_run=False)

    # Still passes the constraint: the row is re-checked on the next update.
    db.execute("""UPDATE outbound_artifact SET content = content
                  WHERE id = %s""", (artifact_id,))


def test_a_tombstoned_artefact_is_not_offered_again(db):
    """Otherwise every sweep re-reports rows it has already handled, and the
    preview fills with work that is already done."""
    artifact_id = a_message(db)
    age_artifact(db, artifact_id)
    retention.apply(db, dry_run=False)
    assert retention.due(db) == []


def test_a_tombstone_matches_no_real_person(db):
    """It goes in a column the suppression check reads. A value that could
    collide with somebody's name would suppress a stranger."""
    from crown import suppression
    assert suppression.normalise("[removed: retention period expired]") \
        != suppression.normalise("A. Landholder")
    artifact_id = a_message(db)
    age_artifact(db, artifact_id)
    retention.apply(db, dry_run=False)

    assert suppression.check(db, {"PERSON": "A. Landholder"}) == []
