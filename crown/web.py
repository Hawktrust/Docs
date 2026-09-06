"""The thin loop's user interface and HTTP surface.

Every request follows the same shape:

  1. read the user id from the signed session cookie
  2. load that user, and their role, from the database
  3. bind the connection to that identity so row-level security applies
  4. authorise the action against the role from step 2

Nothing in that sequence consults a request header. A client may send
X-Crown-Role: ADMIN on every request and it will change nothing.
"""
import os
from datetime import date
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)

from . import approval, attribution, auth, db, matching, opportunity, outbound

SYNTHETIC_LABEL = "DEMO / SYNTHETIC DATA"


def create_app(dsn: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("CROWN_SECRET") or os.urandom(32).hex()
    app.config["DSN"] = dsn or os.environ.get("CROWN_DSN")

    # ---------------------------------------------------------- request cycle

    @app.before_request
    def _open_connection():
        g.conn = db.connect(app.config["DSN"])
        # Identity comes from the signed cookie, and the role from the database.
        # request.headers is deliberately not consulted here or anywhere below.
        g.identity = auth.load(g.conn, session.get("user_id", ""))
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
        return {"identity": g.get("identity"), "synthetic_label": SYNTHETIC_LABEL}

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
                    abort(403)
                return view(*a, **kw)
            return wrapper
        return decorator

    # ---------------------------------------------------------------- routes

    @app.get("/")
    def index():
        return redirect(url_for("opportunities") if g.get("identity") else url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            try:
                identity = auth.authenticate(g.conn, request.form.get("email", "").strip())
            except auth.AuthenticationFailed as exc:
                flash(str(exc))
                return render_template("login.html"), 401
            # Only the user id goes in the cookie. The role is looked up fresh
            # on every subsequent request.
            session["user_id"] = identity.user_id
            return redirect(url_for("opportunities"))
        return render_template("login.html")

    @app.post("/logout")
    def logout():
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

        if decision == "APPROVED":
            attribution.progress(g.conn, approval_id)
        return redirect(url_for("queue"))

    @app.post("/outbound")
    @role_required("ADMIN", "ANALYST", "AGENT")
    def create_outbound():
        """AC8: an export or outreach draft without a usable approval id fails here,
        server-side, before the database is asked."""
        try:
            artifact_id = outbound.create(
                g.conn,
                request.form.get("approval_id") or None,
                request.form.get("artifact_type", "EXPORT"),
                {"note": request.form.get("note", "")},
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
