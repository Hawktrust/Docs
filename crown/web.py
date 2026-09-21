"""The thin loop's user interface and HTTP surface.

Every request follows the same shape:

  1. read the user id from the signed session cookie
  2. load that user, and their role, from the database
  3. bind the connection to that identity so row-level security applies
  4. authorise the action against the role from step 2

Nothing in that sequence consults a request header. A client may send
X-Crown-Role: ADMIN on every request and it will change nothing.
"""
import hmac
import os
import secrets
from datetime import date, datetime, timezone
from functools import wraps

import psycopg
from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)

from . import (alerts, approval, attribution, audit, auth, brief, db, land,
               matching, opportunity, optout, outbound, readiness, reports,
               signals)

SYNTHETIC_LABEL = "DEMO / SYNTHETIC DATA"
ACTOR_AGENT = "crown.web"


class InsecureConfiguration(Exception):
    """The app refuses to start in a state that would quietly weaken it."""


def create_app(dsn: str | None = None) -> Flask:
    app = Flask(__name__)

    # A generated secret would work and would silently invalidate every session
    # on restart, and differ between processes behind a load balancer. Refuse
    # rather than paper over it; tests and local runs set CROWN_SECRET.
    secret = os.environ.get("CROWN_SECRET")
    if not secret:
        raise InsecureConfiguration(
            "CROWN_SECRET is not set. Set it to a long random value; it signs "
            "the session cookie that carries the authenticated user id."
        )
    app.config["SECRET_KEY"] = secret
    app.config["DSN"] = dsn or os.environ.get("CROWN_DSN")

    # Opt-out links have to keep working for thirty days after a message; the
    # session cookie wants rotating far more often than that. Signing both with
    # one secret made a routine rotation into a Spam Act breach, so they are
    # separate, and the old secrets stay accepted for verification while links
    # posted under them are still alive. See crown/optout.py.
    signing, previous = optout.secrets_from_environment()
    app.config["OPT_OUT_SECRETS"] = [signing] + previous

    app.config.update(
        # The cookie carries the identity every authorisation decision is made
        # from, so it does not go to script, does not ride cross-site requests,
        # and outside development does not travel in clear.
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=os.environ.get("CROWN_INSECURE_COOKIES") != "1",
        PERMANENT_SESSION_LIFETIME=auth.SESSION_IDLE_TIMEOUT,
    )

    # ---------------------------------------------------------- request cycle

    def _session_is_stale() -> bool:
        """An unattended browser stops being an approver after the idle timeout."""
        last_seen = session.get("last_seen")
        if not last_seen:
            return False
        try:
            seen_at = datetime.fromisoformat(last_seen)
        except ValueError:
            return True
        return datetime.now(timezone.utc) - seen_at > auth.SESSION_IDLE_TIMEOUT

    @app.before_request
    def _open_connection():
        g.conn = db.connect(app.config["DSN"])
        # Identity comes from the signed cookie, and the role from the database.
        # request.headers is deliberately not consulted here or anywhere below.
        if _session_is_stale():
            session.clear()
        g.identity = auth.load(g.conn, session.get("user_id", ""))
        if g.identity is not None:
            session["last_seen"] = datetime.now(timezone.utc).isoformat()
        db.set_identity(
            g.conn,
            g.identity.user_id if g.identity else "",
            g.identity.role if g.identity else "",
        )

    @app.teardown_request
    def _close_connection(exc):
        conn = g.pop("conn", None)
        if conn is not None:
            if exc is None:
                conn.commit()
            else:
                conn.rollback()
            conn.close()

    @app.context_processor
    def _template_globals():
        return {"identity": g.get("identity"), "synthetic_label": SYNTHETIC_LABEL,
                "csrf_token": _csrf_token()}

    # ------------------------------------------------------ cross-site forgery
    #
    # Approving a match is the act the whole system exists to gate. Without a
    # token, any page a signed-in approver visits could post an approval on
    # their behalf. SameSite=Strict above blocks the common case; this makes it
    # not depend on the browser.

    def _csrf_token() -> str:
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]

    @app.before_request
    def _check_csrf():
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return None
        if request.endpoint == "login":       # no session to protect yet
            return None
        if g.get("identity") is None:
            # Nothing to forge on behalf of. Let the view answer 401 so "who are
            # you" and "you may not" stay distinguishable.
            return None
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf_token", "")
        if not expected or not hmac.compare_digest(sent, expected):
            abort(403, "missing or invalid CSRF token")
        return None

    # ---------------------------------------------------------- authorisation

    def login_required(view):
        @wraps(view)
        def wrapper(*a, **kw):
            if g.get("identity") is None:
                abort(401)
            return view(*a, **kw)
        return wrapper

    def role_required(*roles):
        def decorator(view):
            @wraps(view)
            @login_required
            def wrapper(*a, **kw):
                if not g.identity.has_role(*roles):
                    # The role compared here came from the database in
                    # _open_connection, never from the request.
                    #
                    # A refused attempt is worth more to an auditor than a
                    # permitted one, so it is recorded before the refusal.
                    audit.write(g.conn, audit.new_correlation_id(),
                                "AUTHORISATION_DENIED", "app_user",
                                g.identity.user_id,
                                new_state={"endpoint": request.endpoint,
                                           "method": request.method,
                                           "role_held": g.identity.role,
                                           "roles_required": list(roles)},
                                actor_user_id=g.identity.user_id,
                                actor_agent=ACTOR_AGENT)
                    g.conn.commit()
                    abort(403)
                return view(*a, **kw)
            return wrapper
        return decorator

    # ---------------------------------------------------------------- routes

    @app.get("/")
    def index():
        return redirect(url_for("overview") if g.get("identity") else url_for("login"))

    @app.get("/overview")
    @login_required
    def overview():
        """The honest state of the system, zeros included."""
        return render_template("overview.html", o=reports.overview(g.conn))

    @app.get("/compliance")
    @role_required("ADMIN", "COMPLIANCE")
    def compliance():
        return render_template(
            "compliance.html",
            exceptions=reports.data_rights_exceptions(g.conn),
            queue=reports.unresolved_review_queue(g.conn),
            weights=reports.scoring_weight_history(g.conn),
            trail=reports.audit_trail(g.conn, limit=100))

    @app.get("/health")
    def health():
        """Is the process up and can it reach the database?

        Unauthenticated, because whatever checks it — a load balancer, a
        monitor, a deploy script — has no session. It therefore says nothing a
        stranger should not know: no version, no hostname, no counts, no
        configuration. Up or not up.
        """
        try:
            g.conn.execute("SELECT 1").fetchone()
        except psycopg.Error:
            return {"status": "unhealthy"}, 503
        return {"status": "ok"}, 200

    @app.get("/readiness")
    @role_required("ADMIN", "COMPLIANCE")
    def readiness_page():
        """May Crown be turned on? One answer, not several half-answers."""
        return render_template("readiness.html",
                               report=readiness.check(g.conn))

    # ------------------------------------------------------------- the way out
    #
    # The only unauthenticated route in the application that changes anything,
    # and it exists because APP 7.3 and section 18 of the Spam Act both require
    # the recipient to be able to stop a message themselves. An opt-out behind
    # a sign-in is neither simple nor functional.
    #
    # GET shows a confirmation and changes nothing. Mail scanners and link
    # previewers fetch URLs without a human ever seeing them, and a GET that
    # suppressed would quietly record opt-outs nobody asked for — safe in
    # direction, wrong in fact, and it would corrupt the one record that proves
    # the mechanism works. The POST is what acts.
    #
    # CSRF is not checked here and must not be: there is no session to forge
    # against, and the worst a forged request achieves is that somebody stops
    # being contacted. _check_csrf already returns early when nobody is signed
    # in, which is exactly this case.

    @app.get("/opt-out/<token>")
    def opt_out_confirm(token):
        try:
            optout.read(app.config["OPT_OUT_SECRETS"], token)
        except optout.BadToken as exc:
            return render_template("opt_out.html", state="bad",
                                   message=str(exc)), 400
        # The page deliberately does not name the person or repeat the
        # identifier back. Anyone holding the link can already read it; echoing
        # it turns a shoulder-surf into a disclosure for no benefit.
        return render_template("opt_out.html", state="confirm", token=token)

    @app.post("/opt-out/<token>")
    def opt_out_record(token):
        try:
            optout.redeem(g.conn, app.config["OPT_OUT_SECRETS"], token,
                          requested_at=datetime.now(timezone.utc))
        except optout.BadToken as exc:
            return render_template("opt_out.html", state="bad",
                                   message=str(exc)), 400
        return render_template("opt_out.html", state="done")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            try:
                identity = auth.authenticate(
                    g.conn,
                    request.form.get("email", "").strip(),
                    request.form.get("password", ""))
            except auth.AuthenticationFailed as exc:
                audit.write(g.conn, audit.new_correlation_id(), "SIGN_IN_FAILED",
                            "app_user", request.form.get("email", "")[:200],
                            new_state={"reason": str(exc),
                                       "locked": isinstance(exc, auth.AccountLocked)},
                            actor_agent=ACTOR_AGENT)
                # the attempt counter is part of the same transaction
                g.conn.commit()
                flash(str(exc))
                return render_template("login.html"), 401
            # Only the user id goes in the cookie. The role is looked up fresh
            # on every subsequent request.
            # A new session on every sign-in: an attacker who fixed a session
            # id before the user signed in does not inherit the signed-in one.
            session.clear()
            session["user_id"] = identity.user_id
            session["signed_in_at"] = datetime.now(timezone.utc).isoformat()
            session["last_seen"] = session["signed_in_at"]
            session.permanent = True
            audit.write(g.conn, audit.new_correlation_id(), "SIGN_IN", "app_user",
                        identity.user_id, new_state={"role": identity.role},
                        actor_user_id=identity.user_id, actor_agent=ACTOR_AGENT)
            return redirect(url_for("overview"))
        return render_template("login.html")

    @app.post("/logout")
    def logout():
        if g.get("identity"):
            audit.write(g.conn, audit.new_correlation_id(), "SIGN_OUT", "app_user",
                        g.identity.user_id, actor_user_id=g.identity.user_id,
                        actor_agent=ACTOR_AGENT)
            g.conn.commit()
        session.clear()
        return redirect(url_for("login"))

    @app.get("/opportunities")
    @login_required
    def opportunities():
        rows = g.conn.execute(
            """SELECT o.id, o.lga, o.geography_label, o.stage::text, o.stage_rule,
                      u.display_name, o.next_action,
                      (SELECT count(*) FROM opportunity_evidence oe
                        WHERE oe.opportunity_id = o.id)
               FROM opportunity o JOIN app_user u ON u.id = o.owner_user_id
               ORDER BY o.lga, o.geography_label"""
        ).fetchall()
        return render_template("opportunities.html", rows=rows,
                               rule=opportunity.RULE_DESCRIPTION)

    @app.get("/opportunities/<uuid:opportunity_id>")
    @login_required
    def opportunity_detail(opportunity_id):
        row = g.conn.execute(
            """SELECT o.id, o.lga, o.geography_label, o.stage::text, o.stage_rule,
                      u.display_name
               FROM opportunity o JOIN app_user u ON u.id = o.owner_user_id
               WHERE o.id = %s""",
            (opportunity_id,),
        ).fetchone()
        if row is None:
            abort(404)

        weights = matching.active_weights(g.conn)
        # Read-only: showing a ranking does not write one. Storing is the
        # explicit action below.
        scores = matching.evaluate(g.conn, opportunity_id, as_of=date.today())
        evidence = g.conn.execute(
            """SELECT e.source_reference, e.title, e.evidence_class::text,
                      e.source_url, e.retrieved_at
               FROM opportunity_evidence oe JOIN evidence_record e ON e.id = oe.evidence_id
               WHERE oe.opportunity_id = %s ORDER BY e.observed_at DESC""",
            (opportunity_id,),
        ).fetchall()

        return render_template("opportunity.html", o=row, scores=scores,
                               weights=weights, evidence=evidence,
                               factors=matching.FACTORS)

    @app.post("/opportunities/<uuid:opportunity_id>/rematch")
    @role_required("ADMIN", "ANALYST")
    def rematch(opportunity_id):
        """Recompute and store the ranking, putting its matches in the queue."""
        matching.rank(g.conn, opportunity_id, as_of=date.today(),
                      actor_user_id=g.identity.user_id)
        return redirect(url_for("opportunity_detail", opportunity_id=opportunity_id))

    @app.get("/land")
    @login_required
    def land_search():
        """The prospecting query: council, suburb, acreage, zoning, overlays,
        planning status, dwelling."""
        def as_list(name):
            raw = request.args.get(name, "").strip()
            return [v.strip().upper() for v in raw.split(",") if v.strip()]

        def as_float(name):
            raw = request.args.get(name, "").strip()
            try:
                return float(raw) if raw else None
            except ValueError:
                return None

        dwelling = request.args.get("dwelling", "")
        query = land.LandQuery(
            lga=request.args.get("lga", "").strip() or None,
            locality=request.args.get("locality", "").strip() or None,
            min_acres=as_float("min_acres"),
            max_acres=as_float("max_acres"),
            zone_codes=as_list("zones"),
            any_overlay=as_list("overlays"),
            exclude_overlay=as_list("exclude_overlays"),
            planning_status=as_list("status"),
            has_dwelling={"yes": True, "no": False}.get(dwelling),
            include_crown_land=request.args.get("crown") == "1",
            include_demo=request.args.get("demo") == "1",
        )
        return render_template("land.html", q=query, args=request.args,
                               found=land.search(g.conn, query),
                               statuses=land.PLANNING_STATUSES)

    @app.get("/land/<uuid:parcel_id>/nearby")
    @login_required
    def land_nearby(parcel_id):
        radius = min(int(request.args.get("radius", 2000)), 20000)
        return render_template("nearby.html", parcel_id=parcel_id, radius=radius,
                               rows=land.nearby(g.conn, parcel_id, radius))

    @app.get("/signals")
    @login_required
    def market_signals():
        """Where money is moving, ranked, with every score decomposable."""
        lga = request.args.get("lga", "").strip() or None
        ranked = signals.hotspots(g.conn, lga=lga,
                                 include_demo=request.args.get("demo") == "1")
        return render_template("signals.html", ranked=ranked, lga=lga,
                               weights=signals.active_weights(g.conn),
                               government=signals.government_intent(g.conn, lga=lga))

    @app.get("/alerts")
    @login_required
    def alert_list():
        return render_template(
            "alerts.html",
            rows=alerts.pending(g.conn, g.identity.user_id),
            suppressed=g.conn.execute(
                """SELECT kind::text, detected_event, suppressed_reason, created_at
                   FROM alert WHERE suppressed_reason IS NOT NULL
                   ORDER BY created_at DESC LIMIT 25""").fetchall(),
            watching=g.conn.execute(
                """SELECT kind::text, label, target FROM watchlist
                   WHERE user_id = %s AND is_active ORDER BY kind, label""",
                (g.identity.user_id,)).fetchall())

    @app.post("/alerts/run")
    @role_required("ADMIN", "ANALYST")
    def alert_run():
        report = alerts.run(g.conn)
        flash(f"Alert pass: {report.summary()}")
        return redirect(url_for("alert_list"))

    @app.post("/watchlist")
    @login_required
    def watchlist_add():
        kind = request.form.get("kind", "LGA")
        target = request.form.get("target", "").strip()
        if not target:
            flash("a watch needs something to watch")
            return redirect(url_for("alert_list"))
        g.conn.execute(
            """INSERT INTO watchlist (user_id, kind, target, label)
               VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
            (g.identity.user_id, kind, target,
             request.form.get("label", "").strip() or target))
        return redirect(url_for("alert_list"))

    @app.get("/brief/<uuid:recommendation_id>")
    @login_required
    def investment_brief(recommendation_id):
        try:
            return render_template("brief.html",
                                   b=brief.build(g.conn, recommendation_id))
        except LookupError:
            abort(404)

    @app.get("/mandates")
    @login_required
    def mandates():
        rows = g.conn.execute(
            """SELECT id, buyer_label, origin::text, geographies, asset_types,
                      price_min_aud, price_max_aud, mandate_date, is_active
               FROM buyer_mandate ORDER BY buyer_label"""
        ).fetchall()
        # AC7: every count a person is shown comes from the real view, so the
        # twenty demo records cannot inflate a figure.
        real_count = g.conn.execute("SELECT count(*) FROM buyer_mandate_real").fetchone()[0]
        return render_template("mandates.html", rows=rows, real_count=real_count,
                               shown=len(rows))

    @app.get("/queue")
    @login_required
    def queue():
        return render_template("queue.html", rows=approval.queue(g.conn))

    @app.get("/queue/<uuid:match_result_id>")
    @login_required
    def queue_item(match_result_id):
        row = g.conn.execute(
            """SELECT m.id, m.total_score, b.buyer_label, b.origin::text,
                      o.lga, o.geography_label, o.stage::text, o.stage_rule
               FROM match_result m
               JOIN buyer_mandate b ON b.id = m.buyer_mandate_id
               JOIN opportunity o   ON o.id = m.opportunity_id
               WHERE m.id = %s""",
            (match_result_id,),
        ).fetchone()
        if row is None:
            abort(404)
        return render_template("match.html", m=row,
                               pack=approval.evidence_pack(g.conn, match_result_id))

    @app.post("/queue/<uuid:match_result_id>/decide")
    @role_required("ADMIN", "COMPLIANCE")
    def decide(match_result_id):
        decision = request.form.get("decision", "")
        reason = request.form.get("reason", "")
        if decision not in ("APPROVED", "REJECTED"):
            abort(400)
        try:
            approval_id = approval.decide(
                g.conn, match_result_id, decision, reason,
                g.identity.user_id, g.identity.role)
        except (approval.NotAuthorised, ValueError) as exc:
            flash(str(exc))
            return redirect(url_for("queue_item", match_result_id=match_result_id))
        except psycopg.errors.UniqueViolation:
            # Someone already decided this match — a double submit, or a second
            # approver arriving at the same moment. The first decision stands.
            g.conn.rollback()
            flash("This match has already been decided. The first decision stands.")
            return redirect(url_for("queue")), 409

        if decision == "APPROVED":
            attribution.progress(g.conn, approval_id)
        return redirect(url_for("queue"))

    @app.post("/outbound")
    @role_required("ADMIN", "ANALYST", "AGENT")
    def create_outbound():
        """AC8: an export or outreach draft without a usable approval id fails here,
        server-side, before the database is asked."""
        try:
            approval_id = request.form.get("approval_id") or None
            artifact_id = outbound.create(
                g.conn,
                approval_id,
                request.form.get("artifact_type", "EXPORT"),
                outbound.build_content(g.conn, approval_id,
                                       note=request.form.get("note", "")),
                g.identity.user_id,
            )
        except outbound.ApprovalRequired as exc:
            return {"error": str(exc)}, 403
        except ValueError as exc:
            return {"error": str(exc)}, 400
        return {"artifact_id": str(artifact_id)}, 201

    @app.get("/attribution/<uuid:attribution_id>")
    @login_required
    def attribution_detail(attribution_id):
        row = attribution.trace(g.conn, attribution_id)
        if row is None:
            abort(404)
        return render_template("attribution.html", a=row)

    return app


app = create_app() if os.environ.get("CROWN_DSN") else None
