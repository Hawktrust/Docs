"""Acceptance criteria 5 and 6, and the no-LLM requirement in ticket item 5."""
import inspect
from datetime import date

import pytest

from crown import matching, opportunity
from tests.conftest import add_evidence, user_id


def an_opportunity(db, suburb="Tarneit", lga="Wyndham"):
    add_evidence(db, reference=f"TEST-{suburb}", lga=lga, suburb=suburb)
    owner = user_id(db, "analyst@crown.local")
    return opportunity.refresh(db, owner)[0].opportunity_id


AS_OF = date(2026, 9, 6)


def test_scoring_uses_exactly_five_factors(db):
    oid = an_opportunity(db)
    scores = matching.rank(db, oid, as_of=AS_OF)
    for score in scores:
        assert [f.name for f in score.factors] == list(matching.FACTORS)
        assert len(score.factors) == 5


def test_ranked_buyers_show_every_factor_contribution(db):
    """AC5, first half: per-factor contributions are visible."""
    oid = an_opportunity(db)
    scores = matching.rank(db, oid, as_of=AS_OF)
    included = [s for s in scores if not s.is_excluded]
    assert included, "no mandate matched the opportunity at all"

    for score in included:
        for factor in score.factors:
            assert factor.note, f"{factor.name} gives no account of itself"
            if factor.determinable:
                assert factor.contribution == pytest.approx(factor.weight * factor.raw)

    # and the contributions are persisted, not just returned
    stored = db.execute(
        """SELECT geographic_fit_score, asset_fit_score, price_fit_score,
                  size_fit_score, freshness_score
           FROM match_result WHERE NOT is_excluded LIMIT 1"""
    ).fetchone()
    assert stored is not None and len(stored) == 5


def test_excluded_mandates_carry_a_why_not(db):
    """AC5, second half: a why-not for at least one excluded mandate."""
    oid = an_opportunity(db)
    scores = matching.rank(db, oid, as_of=AS_OF)
    excluded = [s for s in scores if s.is_excluded]
    assert excluded, "the seed set should exclude some mandates from a Wyndham opportunity"
    for score in excluded:
        assert score.why_not

    # the seeds contain both kinds of exclusion
    reasons = " | ".join(s.why_not or "" for s in excluded)
    assert "do not cover Wyndham" in reasons
    assert "not active" in reasons

    stored = db.execute(
        "SELECT count(*) FROM match_result WHERE is_excluded AND why_not IS NOT NULL"
    ).fetchone()[0]
    assert stored == len(excluded)


def test_ranking_is_ordered_by_score(db):
    oid = an_opportunity(db)
    scores = [s for s in matching.rank(db, oid, as_of=AS_OF) if not s.is_excluded]
    assert scores == sorted(scores, key=lambda s: -s.total)


def test_changing_a_weight_in_config_changes_the_ranking(db):
    """AC6: without a code change."""
    oid = an_opportunity(db)

    before = [s.buyer_label for s in matching.rank(db, oid, as_of=AS_OF)
              if not s.is_excluded]

    # Configuration only: a new weight row, activated. No code is touched.
    db.execute("UPDATE match_weight_config SET is_active = false WHERE version = 1")
    db.execute(
        """INSERT INTO match_weight_config (version, geographic_fit, asset_fit,
               price_fit, size_fit, mandate_freshness, is_active)
           VALUES (2, 0.050, 0.200, 0.200, 0.150, 0.900, true)"""
    )

    after = [s.buyer_label for s in matching.rank(db, oid, as_of=AS_OF)
             if not s.is_excluded]

    assert before != after, "reweighting freshness above geography changed nothing"
    assert set(before) == set(after), "the same mandates should be present, reordered"

    # both versions are on record, so a past ranking stays reproducible
    versions = {r[0] for r in db.execute(
        "SELECT weight_config_version FROM match_result").fetchall()}
    assert versions == {1, 2}


def test_weights_come_from_config_and_are_not_defaulted_in_code(db):
    oid = an_opportunity(db)
    db.execute("UPDATE match_weight_config SET is_active = false")
    with pytest.raises(RuntimeError, match="no active row"):
        matching.rank(db, oid, as_of=AS_OF)


def test_scoring_is_reproducible(db):
    """Same inputs, same numbers. Ticket item 5: it must be reproducible."""
    oid = an_opportunity(db)
    first = {s.buyer_mandate_id: s.total for s in matching.rank(db, oid, as_of=AS_OF)}
    second = {s.buyer_mandate_id: s.total for s in matching.rank(db, oid, as_of=AS_OF)}
    assert first == second


def test_no_llm_in_the_scoring_path():
    """Ticket item 5: this is arithmetic.

    Asserted structurally rather than by inspection: the scoring module imports
    no model client and makes no network call.
    """
    import ast

    tree = ast.parse(inspect.getsource(matching))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    forbidden = {"anthropic", "openai", "requests", "httpx", "urllib", "http",
                 "socket", "boto3", "google"}
    assert not (imported & forbidden), f"scoring path imports {imported & forbidden}"
    # what it may import: the standard library bits it actually uses, and audit
    assert imported <= {"dataclasses", "datetime", "audit", ""}, imported


def test_indeterminate_factors_are_not_scored_as_zero(db):
    """A factor with nothing to compare against is reported, not silently zeroed.

    At Ticket 01 scope the opportunity carries no asset type, price or land size,
    so three of the five factors cannot be evaluated. Scoring them zero would
    make every mandate look like a poor fit for reasons that are not its fault.
    """
    oid = an_opportunity(db)
    score = next(s for s in matching.rank(db, oid, as_of=AS_OF) if not s.is_excluded)

    assert score.factor("geographic_fit").determinable
    assert score.factor("mandate_freshness").determinable
    for name in ("asset_fit", "price_fit", "size_fit"):
        factor = score.factor(name)
        assert not factor.determinable
        assert "Ticket 01 scope" in factor.note

    # the total is the weighted mean over what could be evaluated
    usable = score.determinable_weight
    expected = sum(f.contribution for f in score.factors) / usable
    assert score.total == pytest.approx(round(expected, 4))
