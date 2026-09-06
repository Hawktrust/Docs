"""Ticket item 5: a transparent scoring function over exactly five factors.

Geographic fit, asset fit, price fit, size fit, mandate freshness. Nothing else
contributes to a score.

Three properties the ticket asks for, and how they are met:

  weights live in config          the five numbers come from the active row of
                                  match_weight_config. Changing one and
                                  activating the new version changes the
                                  ranking with no code change.

  every contribution is shown     scoring returns a FactorScore per factor,
                                  each stored on match_result and rendered.

  no LLM in the scoring path      this module is arithmetic. It imports no
                                  model client, makes no network call, and
                                  given the same inputs returns the same
                                  numbers every time.

A note on Ticket 01 scope: an opportunity here is geographic and carries no
asset type, price or land size — that is Gate 0 work. Three of the five factors
therefore have nothing on the opportunity side to compare against. They are
reported as INDETERMINATE rather than scored zero, and the total is the weighted
mean over the factors that could actually be evaluated. Scoring an unknown as
zero would quietly punish every mandate equally and make the number look more
informed than it is.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import audit

ACTOR_AGENT = "crown.matching"

FACTORS = ("geographic_fit", "asset_fit", "price_fit", "size_fit", "mandate_freshness")

# A mandate stops counting as fresh after two years. Linear decay in between.
FRESHNESS_HORIZON = timedelta(days=730)


@dataclass
class FactorScore:
    name: str
    raw: float                 # 0..1, or 0.0 when indeterminate
    weight: float
    determinable: bool
    note: str

    @property
    def contribution(self) -> float:
        """What this factor actually added to the total, before normalisation."""
        return self.weight * self.raw if self.determinable else 0.0


@dataclass
class MatchScore:
    buyer_mandate_id: str
    buyer_label: str
    origin: str
    total: float
    factors: list[FactorScore]
    is_excluded: bool = False
    why_not: str | None = None

    def factor(self, name: str) -> FactorScore:
        return next(f for f in self.factors if f.name == name)

    @property
    def determinable_weight(self) -> float:
        return sum(f.weight for f in self.factors if f.determinable)


@dataclass
class OpportunityProfile:
    """What the matcher knows about an opportunity.

    At Ticket 01 scope only the geography is populated. The other three are
    carried explicitly as None so the scoring function reports them as
    indeterminate instead of pretending to a number.
    """
    lga: str
    geography_label: str
    asset_types: list[str] | None = None
    price_aud: int | None = None
    land_size_sqm: int | None = None


@dataclass
class Weights:
    version: int
    geographic_fit: float
    asset_fit: float
    price_fit: float
    size_fit: float
    mandate_freshness: float

    def of(self, factor: str) -> float:
        return float(getattr(self, factor))


def active_weights(conn) -> Weights:
    row = conn.execute(
        """SELECT version, geographic_fit, asset_fit, price_fit, size_fit,
                  mandate_freshness
           FROM match_weight_config WHERE is_active"""
    ).fetchone()
    if row is None:
        raise RuntimeError(
            "no active row in match_weight_config: the scoring weights are "
            "configuration and the matcher will not invent them"
        )
    return Weights(int(row[0]), *(float(v) for v in row[1:]))


# ---------------------------------------------------------------- the factors

# A mandate naming one geography fits a given geography better than a mandate
# naming five. Specificity is part of geographic fit, so a broad mandate is
# discounted: 1 / (1 + FOCUS_PENALTY * (geographies - 1)).
FOCUS_PENALTY = 0.15


def _geographic_fit(profile, mandate, weight) -> FactorScore:
    """How well the mandate's stated geography matches this opportunity.

    Naming the precinct itself beats naming only the surrounding LGA, and a
    tightly drawn mandate beats a scattergun one.
    """
    stated = list(mandate["geographies"] or [])          # as the mandate wrote them
    wanted = {g.strip().lower() for g in stated}          # for comparison only
    label = profile.geography_label.strip().lower()
    lga = profile.lga.strip().lower()

    if label in wanted:
        base, how = 1.0, f"names the precinct {profile.geography_label}"
    elif lga in wanted:
        base, how = 0.7, f"names the LGA {profile.lga} but not {profile.geography_label}"
    else:
        return FactorScore(
            "geographic_fit", 0.0, weight, True,
            f"mandate covers {sorted(stated)}, which does not include {profile.lga}",
        )

    focus = 1.0 / (1.0 + FOCUS_PENALTY * (len(wanted) - 1))
    return FactorScore(
        "geographic_fit", round(base * focus, 4), weight, True,
        f"{how}; mandate spans {len(wanted)} geograph{'y' if len(wanted) == 1 else 'ies'}",
    )


def _asset_fit(profile, mandate, weight) -> FactorScore:
    if not profile.asset_types:
        return FactorScore(
            "asset_fit", 0.0, weight, False,
            "the opportunity carries no asset type at Ticket 01 scope",
        )
    wanted = {a.strip().lower() for a in (mandate["asset_types"] or [])}
    ours = {a.strip().lower() for a in profile.asset_types}
    overlap = wanted & ours
    raw = len(overlap) / len(ours) if ours else 0.0
    return FactorScore("asset_fit", raw, weight, True,
                       f"{len(overlap)} of {len(ours)} opportunity asset type(s) wanted")


def _range_fit(value, low, high, name, weight, unit) -> FactorScore:
    """Full marks inside the band; tapering to zero one band-width outside it."""
    if value is None:
        return FactorScore(name, 0.0, weight, False,
                           f"the opportunity carries no {unit} at Ticket 01 scope")
    if low is None and high is None:
        return FactorScore(name, 0.0, weight, False, f"mandate states no {unit} range")

    low = low if low is not None else value
    high = high if high is not None else value
    if low <= value <= high:
        return FactorScore(name, 1.0, weight, True,
                           f"{value} is inside the mandate band {low}-{high}")

    span = max(high - low, 1)
    distance = (low - value) if value < low else (value - high)
    raw = max(0.0, 1.0 - distance / span)
    return FactorScore(name, raw, weight, True,
                       f"{value} is outside the mandate band {low}-{high} by {distance}")


def _freshness(mandate, weight, as_of: date) -> FactorScore:
    mandate_date = mandate["mandate_date"]
    age = as_of - mandate_date
    if age < timedelta(0):
        raw = 1.0
    else:
        raw = max(0.0, 1.0 - age / FRESHNESS_HORIZON)
    return FactorScore("mandate_freshness", raw, weight, True,
                       f"mandate dated {mandate_date}, {age.days} days old at {as_of}")


# ---------------------------------------------------------------- the function

def score(profile: OpportunityProfile, mandate: dict, weights: Weights,
          as_of: date) -> MatchScore:
    """Score one mandate against one opportunity. Pure arithmetic."""
    factors = [
        _geographic_fit(profile, mandate, weights.of("geographic_fit")),
        _asset_fit(profile, mandate, weights.of("asset_fit")),
        _range_fit(profile.price_aud, mandate["price_min_aud"], mandate["price_max_aud"],
                   "price_fit", weights.of("price_fit"), "price"),
        _range_fit(profile.land_size_sqm, mandate["land_size_min_sqm"],
                   mandate["land_size_max_sqm"], "size_fit", weights.of("size_fit"),
                   "land size"),
        _freshness(mandate, weights.of("mandate_freshness"), as_of),
    ]

    usable = sum(f.weight for f in factors if f.determinable)
    total = (sum(f.contribution for f in factors) / usable) if usable else 0.0

    result = MatchScore(
        buyer_mandate_id=mandate["id"],
        buyer_label=mandate["buyer_label"],
        origin=mandate["origin"],
        total=round(total, 4),
        factors=factors,
    )

    # why-not: the reasons a mandate is not a candidate at all, as opposed to
    # simply scoring low.
    reasons = []
    if not mandate["is_active"]:
        reasons.append("mandate is not active")
    if result.factor("geographic_fit").raw == 0.0:
        reasons.append(
            f"mandate geographies {sorted(mandate['geographies'])} do not cover "
            f"{profile.lga}"
        )
    if reasons:
        result.is_excluded = True
        result.why_not = "; ".join(reasons)

    return result


def evaluate(conn, opportunity_id, *, as_of: date | None = None) -> list[MatchScore]:
    """Score every mandate against one opportunity and return the ranking.

    Reads only. Displaying a ranking must not change the database, so the page
    that shows one calls this; recomputing and storing is a separate, explicit
    action.
    """
    as_of = as_of or date.today()
    weights = active_weights(conn)

    row = conn.execute(
        "SELECT lga, geography_label FROM opportunity WHERE id = %s", (opportunity_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"no opportunity {opportunity_id}")
    profile = OpportunityProfile(lga=row[0], geography_label=row[1])

    mandates = conn.execute(
        """SELECT id, buyer_label, origin::text, geographies, asset_types,
                  land_size_min_sqm, land_size_max_sqm, price_min_aud, price_max_aud,
                  mandate_date, is_active
           FROM buyer_mandate"""
    ).fetchall()
    columns = ("id", "buyer_label", "origin", "geographies", "asset_types",
               "land_size_min_sqm", "land_size_max_sqm", "price_min_aud",
               "price_max_aud", "mandate_date", "is_active")

    results = [score(profile, dict(zip(columns, m)), weights, as_of) for m in mandates]
    results.sort(key=lambda r: (r.is_excluded, -r.total))
    return results


def rank(conn, opportunity_id, *, as_of: date | None = None,
         correlation_id=None, actor_user_id=None) -> list[MatchScore]:
    """Evaluate the ranking and store it, so the approval queue can be built."""
    correlation_id = correlation_id or audit.new_correlation_id()
    weights = active_weights(conn)
    results = evaluate(conn, opportunity_id, as_of=as_of)

    for result in results:
        conn.execute(
            """
            INSERT INTO match_result (opportunity_id, buyer_mandate_id,
                weight_config_version, total_score, geographic_fit_score,
                asset_fit_score, price_fit_score, size_fit_score, freshness_score,
                is_excluded, why_not)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (opportunity_id, buyer_mandate_id, weight_config_version)
            DO UPDATE SET total_score = EXCLUDED.total_score,
                          geographic_fit_score = EXCLUDED.geographic_fit_score,
                          asset_fit_score = EXCLUDED.asset_fit_score,
                          price_fit_score = EXCLUDED.price_fit_score,
                          size_fit_score = EXCLUDED.size_fit_score,
                          freshness_score = EXCLUDED.freshness_score,
                          is_excluded = EXCLUDED.is_excluded,
                          why_not = EXCLUDED.why_not,
                          computed_at = now()
            """,
            (opportunity_id, result.buyer_mandate_id, weights.version, result.total,
             result.factor("geographic_fit").contribution,
             result.factor("asset_fit").contribution,
             result.factor("price_fit").contribution,
             result.factor("size_fit").contribution,
             result.factor("mandate_freshness").contribution,
             result.is_excluded, result.why_not),
        )

    audit.write(conn, correlation_id, "MATCHES_COMPUTED", "opportunity", opportunity_id,
                new_state={"weight_config_version": weights.version,
                           "scored": len(results),
                           "excluded": sum(1 for r in results if r.is_excluded)},
                actor_user_id=actor_user_id, actor_agent=ACTOR_AGENT)
    return results
