"""May Crown be turned on?

The register answered one kind of question and the compliance page showed it.
Nothing answered all of them at once, which is what a launch decision needs.

These tests hold two things. That the gate actually blocks — a failing blocking
check makes the whole report not-ready, and the CLI exits non-zero, so a
pipeline can refuse to promote a build nobody looked at. And that it stays
honest about what it does not know: a check that passes because the table is
empty is not the same as a check that passes because the work was done, and the
detail line says which.
"""
from crown import readiness
from scripts import readiness as cli
from tests.conftest import a_body, add_evidence, sign_in, user_id
from tests.test_optout import (an_identity, insert_an_identity,
                               no_active_identity)


def codes(report):
    return {c.code: c for c in report.checks}


# ------------------------------------------------------------- the gate holds

def test_a_fresh_database_is_not_ready(db):
    """Nothing has been ingested and nobody has said who Crown sends as. The
    honest answer to 'may we go live' is no."""
    report = readiness.check(db)
    assert not report.ready
    assert report.blockers


def test_the_blockers_name_what_would_close_them(db):
    """'0 evidence records with origin REAL' is a fact. 'Ingest one real
    amendment' is the next action, and a report without it sends the reader to
    find somebody who knows."""
    for blocker in readiness.check(db).blockers:
        assert blocker.closes_it.strip()
        assert blocker.closes_it != blocker.detail


def test_ac1_is_one_of_the_blockers(db):
    """A system that has never ingested a real record is a demonstration, and
    the readiness gate says so in the same words the acceptance criteria do."""
    real = codes(readiness.check(db))["REAL_EVIDENCE_EXISTS"]
    assert not real.passes
    assert real.blocking

    add_evidence(db, reference="TEST-RDY-1", origin="REAL")
    assert codes(readiness.check(db))["REAL_EVIDENCE_EXISTS"].passes


def test_an_advisory_failure_does_not_block_a_launch(db):
    """That is what advisory means. It still prints."""
    report = readiness.check(db)
    advisory = [c for c in report.checks if not c.blocking]
    assert advisory, "every check is blocking, which makes the severity useless"
    assert all(c in report.checks for c in report.warnings)
    assert all(not c.blocking for c in report.warnings)


def test_failures_are_reported_before_passes(db):
    """The thing that stops a launch does not sit below the thing that does
    not."""
    passes = [c.passes for c in readiness.check(db).checks]
    assert passes == sorted(passes), "a passing check appears above a failing one"


def test_blocking_failures_come_before_advisory_ones(db):
    failing = [c for c in readiness.check(db).checks if not c.passes]
    blocking = [i for i, c in enumerate(failing) if c.blocking]
    advisory = [i for i, c in enumerate(failing) if not c.blocking]
    assert not blocking or not advisory or max(blocking) < min(advisory)


# ------------------------------------------------- the checks that were added

def test_crown_must_know_who_it_sends_as(db):
    """Section 17 of the Spam Act, asked before anything is written rather than
    discovered after it was sent.

    0019 records the real sender, so the failing condition is constructed here.
    What is under test is the check, not whether the seed happens to satisfy
    it."""
    assert codes(readiness.check(db))["CROWN_KNOWS_WHO_IT_SENDS_AS"].passes

    no_active_identity(db)
    check = codes(readiness.check(db))["CROWN_KNOWS_WHO_IT_SENDS_AS"]
    assert not check.passes and check.blocking

    insert_an_identity(db)
    assert codes(readiness.check(db))["CROWN_KNOWS_WHO_IT_SENDS_AS"].passes
    db.rollback()


def test_two_active_senders_is_also_a_failure(db):
    """A recipient who cannot tell which organisation authorised the message is
    the thing s17 exists to prevent. The unique index refuses the second one."""
    import psycopg
    import pytest

    assert an_identity(db) is not None          # 0019 already recorded one
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_an_identity(db)
    db.rollback()


def test_demonstration_data_must_not_have_left(db):
    """The seeded loop runs on synthetic records. They exist to exercise the
    system and must never have gone anywhere."""
    check = codes(readiness.check(db))["NOTHING_SYNTHETIC_HAS_LEFT"]
    assert check.blocking
    assert check.passes, "nothing has been sent yet"


def test_an_artifact_built_on_synthetic_records_fails_the_gate(db):
    """A match is only as real as both sides of it, so the check looks at the
    opportunity and the mandate rather than at the match row."""
    from crown import outbound
    from tests.conftest import approved_match

    an_identity(db)
    approval_id, creator = approved_match(db)
    outbound.create(db, approval_id, "OUTREACH_DRAFT", {"body": a_body()}, creator,
                    contact={"PERSON": "A. Landholder"},
                    channel="POST",
                    recipient_class="LANDHOLDER_FROM_REGISTER")

    check = codes(readiness.check(db))["NOTHING_SYNTHETIC_HAS_LEFT"]
    assert not check.passes
    assert "keep this environment out of production" in check.closes_it


def test_every_account_must_have_a_password(db):
    """0006 left every seeded password NULL so that nobody could be anybody.
    Going live with that still true means the accounts are unusable, not safe."""
    check = codes(readiness.check(db))["EVERY_ACCOUNT_HAS_A_PASSWORD"]
    assert check.blocking

    db.execute("UPDATE app_user SET password_hash = NULL WHERE is_active")
    assert not codes(readiness.check(db))["EVERY_ACCOUNT_HAS_A_PASSWORD"].passes
    db.rollback()


def test_the_data_rights_gate_is_in_here_too(db):
    """The register's own report, folded into the one answer a launch needs."""
    check = codes(readiness.check(db))["DATA_RIGHTS_COMPLETE"]
    assert check.passes and check.blocking

    db.execute("""UPDATE data_source SET register_confirmed_by = NULL
                  WHERE code = 'VIC_PLANNING_AMENDMENTS'""")
    assert not codes(readiness.check(db))["DATA_RIGHTS_COMPLETE"].passes
    db.rollback()


# ------------------------------------------------------------------- the CLI

def test_the_cli_exits_non_zero_while_anything_blocks(database, capsys):
    """So a deploy pipeline can refuse to promote a build without anybody
    having to remember to look."""
    owner_dsn, _ = database
    assert cli.main(["--dsn", owner_dsn]) == 1
    assert "NOT READY" in capsys.readouterr().out


def test_the_cli_prints_what_would_close_each_blocker(database, capsys):
    owner_dsn, _ = database
    cli.main(["--dsn", owner_dsn])
    printed = capsys.readouterr().out
    assert "→" in printed
    assert "operator capture" in printed


def test_quiet_says_nothing_and_still_answers(database, capsys):
    owner_dsn, _ = database
    assert cli.main(["--dsn", owner_dsn, "--quiet"]) == 1
    assert capsys.readouterr().out == ""


def test_without_a_dsn_it_says_so_rather_than_guessing(monkeypatch, capsys):
    monkeypatch.delenv("CROWN_DSN", raising=False)
    assert cli.main([]) == 2
    assert "CROWN_DSN" in capsys.readouterr().err


# ------------------------------------------------------------------ the page

def test_only_admin_and_compliance_see_the_readiness_page(client):
    sign_in(client, "analyst@crown.local")
    assert client.get("/readiness").status_code == 403

    sign_in(client, "compliance@crown.local")
    assert client.get("/readiness").status_code == 200


def test_the_page_shows_the_blockers(client):
    sign_in(client, "compliance@crown.local")
    page = client.get("/readiness")
    assert b"NOT READY" in page.data
    assert b"REAL_EVIDENCE_EXISTS" in page.data
    assert b"operator capture" in page.data


# ------------------------------------- the conditions the database cannot see

def test_the_gate_checks_the_deployment_too(db):
    """launch_readiness reads the database, so it can only ever check what the
    database knows. Two conditions live in the deployment."""
    codes = {c.code for c in readiness.check(db, environ={}).checks}
    assert "OPT_OUT_SECRET_IS_ITS_OWN" in codes
    assert "SESSION_COOKIES_ARE_SECURE" in codes


def test_one_secret_for_cookies_and_opt_outs_blocks_a_launch(db):
    """Rotating it would break every live unsubscribe link, which is a breach
    of s18 rather than an inconvenience."""
    failing = codes(readiness.check(db, environ={"CROWN_SECRET": "x"}))
    check = failing["OPT_OUT_SECRET_IS_ITS_OWN"]
    assert not check.passes and check.blocking
    assert "30-day" in check.closes_it

    passing = codes(readiness.check(db, environ={"CROWN_OPTOUT_SECRET": "y"}))
    assert passing["OPT_OUT_SECRET_IS_ITS_OWN"].passes


def test_insecure_cookies_block_a_launch(db):
    """The flag exists for the test client. In production it strips Secure from
    the cookie that carries every authorisation decision."""
    failing = codes(readiness.check(db, environ={"CROWN_INSECURE_COOKIES": "1"}))
    assert not failing["SESSION_COOKIES_ARE_SECURE"].passes

    assert codes(readiness.check(db, environ={}))["SESSION_COOKIES_ARE_SECURE"].passes


def test_a_person_must_be_answerable(db):
    """APP 1.4 wants somebody contactable for access, correction and
    complaints. An account nobody can sign in to cannot answer anyone."""
    check = codes(readiness.check(db))["SOMEBODY_CAN_ANSWER_A_PERSON"]
    assert check.blocking
    assert not check.passes          # seeded accounts have no password yet

    db.execute("""UPDATE app_user SET password_hash = 'set'
                  WHERE role = 'COMPLIANCE' AND is_active""")
    assert codes(readiness.check(db))["SOMEBODY_CAN_ANSWER_A_PERSON"].passes
    db.rollback()
