"""Each test gets a database built by the real migrations and seeds.

Two connections are offered, because the acceptance criteria need both:

  db      connects as the owner/superuser. Used to set a test up, and to assert
          things about the schema itself.
  app_db  connects as crown_app, the unprivileged role the application actually
          uses. Row-level security applies to it, so this is the only honest way
          to test authorisation.

Fixture records are test data. They live in a throwaway database, they are
prefixed TEST- or flagged DEMO_SYNTHETIC, and they never touch a database a
person reads a figure from.
"""
import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")
MIGRATIONS = [
    os.path.join(ROOT, "migrations", "0001_ticket01_thin_loop.sql"),
    os.path.join(ROOT, "migrations", "0002_rls_policies.sql"),
    os.path.join(ROOT, "migrations", "0003_retrieval_method.sql"),
    os.path.join(ROOT, "migrations", "0004_integrity_fixes.sql"),
    os.path.join(ROOT, "migrations", "0005_audit_and_controls.sql"),
    os.path.join(ROOT, "migrations", "0006_real_authentication.sql"),
    os.path.join(ROOT, "migrations", "0007_personal_information.sql"),
    os.path.join(ROOT, "migrations", "0008_prospecting_controls.sql"),
    os.path.join(ROOT, "migrations", "0009_automated_access.sql"),
    os.path.join(ROOT, "migrations", "0010_land_layer.sql"),
    os.path.join(ROOT, "migrations", "0011_market_signals.sql"),
    os.path.join(ROOT, "migrations", "0012_watchlists_and_alerts.sql"),
    os.path.join(ROOT, "migrations", "0013_close_the_base_tables.sql"),
    os.path.join(ROOT, "migrations", "0014_terms_read.sql"),
    os.path.join(ROOT, "migrations", "0015_councils_and_signature.sql"),
    os.path.join(ROOT, "migrations", "0016_going_live.sql"),
    os.path.join(ROOT, "migrations", "0017_close_the_sender_identity.sql"),
    os.path.join(ROOT, "migrations", "0018_operational_readiness.sql"),
    os.path.join(ROOT, "migrations", "0019_crown_sends_as_itself.sql"),
    os.path.join(ROOT, "migrations", "0020_an_identity_that_means_something.sql"),
]
LEADS_FILE = os.path.join(ROOT, "seeds", "relay_leads.json")
SEEDS = [
    os.path.join(ROOT, "seeds", "001_users_and_config.sql"),
    os.path.join(ROOT, "seeds", "002_buyer_mandates.sql"),
    os.path.join(ROOT, "seeds", "003_candidate_sources.sql"),
]
ADMIN_DSN = os.environ.get("CROWN_ADMIN_DSN",
                           "postgresql://postgres@127.0.0.1:5432/postgres")
APP_PASSWORD = "test-only-password"
# The seeded mandates, all synthetic. One place to update when the seed changes;
# test_the_seed_file_matches_this_count keeps it from drifting silently.
SEEDED_MANDATE_COUNT = 23


def seeded_leads():
    """The shipped relay leads, read from the file rather than counted by hand."""
    import json
    return json.loads(open(LEADS_FILE).read())["leads"]


def _run_sql(dsn, path):
    result = subprocess.run(["psql", "-q", "-v", "ON_ERROR_STOP=1", "-d", dsn, "-f", path],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{os.path.basename(path)} failed:\n{result.stderr}")


@pytest.fixture()
def database():
    """Build a database, hand back its two DSNs, drop it afterwards."""
    name = f"crown_test_{uuid.uuid4().hex[:10]}"
    admin = psycopg.connect(ADMIN_DSN, autocommit=True)
    admin.execute(f'CREATE DATABASE "{name}"')

    base, _ = ADMIN_DSN.rsplit("/", 1)
    owner_dsn = f"{base}/{name}"
    for path in MIGRATIONS + SEEDS:
        _run_sql(owner_dsn, path)

    # crown_app is created by migration 0002 at cluster level; give it a password
    # so the tests can connect over TCP as that role.
    admin.execute(f"ALTER ROLE crown_app WITH PASSWORD '{APP_PASSWORD}'")
    scheme, rest = base.split("://", 1)
    host = rest.split("@", 1)[1]
    app_dsn = f"{scheme}://crown_app:{APP_PASSWORD}@{host}/{name}"

    try:
        yield owner_dsn, app_dsn
    finally:
        admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.close()


@pytest.fixture()
def db(database):
    """Owner connection: setup and schema-level assertions."""
    owner_dsn, _ = database
    conn = psycopg.connect(owner_dsn, autocommit=False)
    yield conn
    conn.close()


@pytest.fixture()
def app_dsn(database):
    return database[1]


@pytest.fixture()
def app_db(database):
    """Application connection: unprivileged, row-level security applies."""
    _, dsn = database
    conn = psycopg.connect(dsn, autocommit=False)
    yield conn
    conn.close()


# ------------------------------------------------------------------ fixtures

class FakeRetrieval:
    def __init__(self, url="https://www.planning.vic.gov.au/guides-and-resources/amendments"):
        self.url = url
        self.retrieved_at = datetime.now(timezone.utc)
        self.status_code = 200
        self.body = ""
        self.content_type = "application/json"


@pytest.fixture()
def retrieval():
    return FakeRetrieval()


def user_id(conn, email):
    return conn.execute("SELECT id FROM app_user WHERE email = %s", (email,)).fetchone()[0]


def add_evidence(conn, *, reference, lga="Wyndham", evidence_class="FACT",
                 suburb="Tarneit", observed_days_ago=20,
                 status="GAZETTED", origin="DEMO_SYNTHETIC"):
    """Insert one evidence record with complete provenance.

    origin defaults to DEMO_SYNTHETIC: these are test records, and the schema
    has a column that says so, so it is used rather than letting a fixture
    masquerade as REAL.
    """
    from psycopg.types.json import Jsonb
    source_id = conn.execute(
        "SELECT id FROM data_source WHERE code = 'VIC_PLANNING_AMENDMENTS'").fetchone()[0]
    now = datetime.now(timezone.utc)
    return conn.execute(
        """
        INSERT INTO evidence_record (source_id, source_reference, source_url, provider,
            retrieved_at, observed_at, last_verified_at, lane, reliability,
            evidence_class, confidence, lga, title, amendment_status, geography, origin)
        VALUES (%s,%s,%s,%s,%s,%s,%s,'B_OPEN','AUTHORITATIVE',%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
        """,
        (source_id, reference, f"https://www.planning.vic.gov.au/amendment/{reference}",
         "State Government of Victoria", now, now - timedelta(days=observed_days_ago),
         now, evidence_class, 1.0 if evidence_class == "FACT" else 0.9, lga,
         f"Test fixture — {reference}", status, Jsonb({"suburbs": [suburb]}), origin),
    ).fetchone()[0]


def approved_match(conn, decision="APPROVED"):
    """One approval, ready to hang an outbound artefact off."""
    from crown import approval, matching, opportunity

    add_evidence(conn, reference="TEST-C030wynd")
    owner = user_id(conn, "analyst@crown.local")
    oid = opportunity.refresh(conn, owner)[0].opportunity_id
    matching.rank(conn, oid)
    match_id = conn.execute(
        "SELECT id FROM match_result WHERE NOT is_excluded "
        "ORDER BY total_score DESC LIMIT 1").fetchone()[0]
    approver = user_id(conn, "compliance@crown.local")
    approval_id = approval.decide(conn, match_id, decision, "checked the pack",
                                  approver, "COMPLIANCE")
    conn.commit()
    return approval_id, approver


@pytest.fixture()
def client(app_dsn, database, monkeypatch):
    """A test client for the web app, connected as the unprivileged app role.

    Seeded users have no password (0006 leaves password_hash NULL, so nobody can
    be them until someone sets one). The fixture gives them a known one.
    """
    import psycopg

    from crown.web import create_app

    owner_dsn, _ = database
    with psycopg.connect(owner_dsn) as setup:
        give_everyone_a_password(setup)

    monkeypatch.setenv("CROWN_SECRET", "test-secret-not-for-production")
    monkeypatch.setenv("CROWN_INSECURE_COOKIES", "1")   # the test client is not https
    app = create_app(app_dsn)
    app.config["TESTING"] = True
    return app.test_client()


TEST_PASSWORD = "test-password-not-a-secret"


def give_everyone_a_password(conn):
    """The seeded users have no password, so they cannot sign in at all.

    Tests that exercise the UI need credentials; this sets the same one for
    every seeded account and commits.
    """
    from crown import auth
    for (email,) in conn.execute("SELECT email FROM app_user").fetchall():
        auth.set_password(conn, email, TEST_PASSWORD)
    conn.commit()


def sign_in(client, email, password=TEST_PASSWORD):
    response = client.post("/login", data={"email": email, "password": password},
                           follow_redirects=False)
    assert response.status_code in (302, 200), response.status_code
    return response


def csrf(client):
    """The token the server issued for this session, as a form field."""
    with client.session_transaction() as session:
        token = session.get("csrf_token")
    if token is None:                      # not yet issued: render a page to mint one
        client.get("/opportunities")
        with client.session_transaction() as session:
            token = session["csrf_token"]
    return {"csrf_token": token}
