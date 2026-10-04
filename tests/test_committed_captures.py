"""Whatever is in captures/ must still import.

A committed bundle is what makes AC1 a property of this repository rather than
something somebody has to redo on every new database. That only holds while the
bundle still loads and still passes the importer — a schema change, a tightened
validation, a renamed field, and it would quietly stop working. Nobody would
notice until the next deployment had no real evidence and the gate said so.

These tests skip when the directory is empty, so the repository is honest about
the difference between "no capture has been taken yet" and "the capture is
broken".
"""
import json
import pathlib

import pytest

from ingest import capture, registry
from tests.conftest import user_id

CAPTURES = sorted(
    (pathlib.Path(__file__).resolve().parent.parent / "captures").glob("*.json"))

needs_a_capture = pytest.mark.skipif(
    not CAPTURES,
    reason="no bundle committed yet — see captures/README.md; AC1 is open")


@needs_a_capture
@pytest.mark.parametrize("path", CAPTURES, ids=lambda p: p.name)
def test_a_committed_bundle_still_loads(path):
    """The shape the importer expects, before touching a database."""
    bundle = capture.load(str(path))
    assert bundle["confirmed_by_operator"] is True
    assert bundle["capture"]["raw_html"]
    assert bundle["records"]


@needs_a_capture
@pytest.mark.parametrize("path", CAPTURES, ids=lambda p: p.name)
def test_the_bytes_match_their_hash(path):
    """The point of keeping the bytes: anything drawn from this page can be
    rechecked against what was actually read, rather than trusted. A bundle
    whose hash does not match its own HTML has been edited after capture, and
    an edited capture is not evidence of anything."""
    bundle = json.loads(path.read_text())
    stated = bundle["capture"]["sha256"]
    assert stated == capture.sha256_of(bundle["capture"]["raw_html"])


@needs_a_capture
@pytest.mark.parametrize("path", CAPTURES, ids=lambda p: p.name)
def test_a_committed_bundle_still_imports(db, path):
    """Into a real database, through the real importer."""
    source = registry.resolve(db, "VIC_PLANNING_AMENDMENTS")
    report = capture.ingest_capture(db, source, capture.load(str(path)),
                                    user_id(db, "analyst@crown.local"))
    assert report.summary()


@needs_a_capture
def test_importing_them_makes_ac1_pass(db):
    """The whole reason the directory exists. REAL_EVIDENCE_EXISTS is the last
    blocking check that needs something from outside this container; a
    committed bundle is what stops it needing that twice."""
    from crown import readiness

    source = registry.resolve(db, "VIC_PLANNING_AMENDMENTS")
    operator = user_id(db, "analyst@crown.local")
    for path in CAPTURES:
        capture.ingest_capture(db, source, capture.load(str(path)), operator)

    by_code = {c.code: c for c in readiness.check(db).checks}
    assert by_code["REAL_EVIDENCE_EXISTS"].passes, by_code["REAL_EVIDENCE_EXISTS"].detail


@needs_a_capture
def test_what_they_produce_is_marked_as_operator_capture(db):
    """Not DIRECT_FETCH. Who looked matters as much as what they saw, and a
    record claiming this system retrieved a page it cannot reach would be
    exactly the provenance failure the rest of the schema exists to prevent."""
    source = registry.resolve(db, "VIC_PLANNING_AMENDMENTS")
    capture.ingest_capture(db, source, capture.load(str(CAPTURES[0])),
                           user_id(db, "analyst@crown.local"))

    methods = {r[0] for r in db.execute(
        "SELECT retrieval_method FROM evidence_record WHERE origin = 'REAL'"
    ).fetchall()}
    assert methods == {"OPERATOR_CAPTURE"}


def test_the_directory_exists_even_when_empty():
    """So that the answer to "where do captures go" is in the repository rather
    than in somebody's memory of a conversation."""
    readme = (pathlib.Path(__file__).resolve().parent.parent
              / "captures" / "README.md")
    assert readme.exists()
    assert "OPERATOR_CAPTURE" in readme.read_text()
