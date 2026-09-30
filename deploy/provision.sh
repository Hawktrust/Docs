#!/usr/bin/env bash
# Take a database and a domain, and leave a system somebody can launch.
#
#   sudo ./deploy/provision.sh \
#        --admin-dsn postgresql://postgres:...@db.example:5432/postgres \
#        --database crown_ai \
#        --domain crown.example.com
#
# Safe to re-run. It provisions what is missing and leaves what exists alone.
#
# It does NOT apply migrations to a database that already has a schema. That is
# deliberate and matches deploy/README.md: migrations are forward-only with no
# down-steps, and the first one applied to a database holding real records is
# where applying them unattended stops being fine. So the first run builds the
# schema and a later run tells you to apply new migrations yourself, having read
# them. The moment where somebody notices is the point.
#
# WHAT IT REFUSES TO DO. It will not finish quietly on a system that is not
# ready. The last thing it does is run the readiness gate as the application
# role, and it exits non-zero if anything blocking fails. A provisioning script
# that reports success on a database nobody may lawfully use is worse than no
# script, because the success is what gets believed.
#
# It does not set a user's password. That is interactive on purpose — a
# credential this script generated would be a credential in a log.
set -euo pipefail

ADMIN_DSN=""; DBNAME="crown_ai"; DOMAIN=""; APP_PASS=""
SRV="${CROWN_SRV:-/srv/crown}"
ENVFILE="${CROWN_ENVFILE:-/etc/crown/crown.env}"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --admin-dsn) ADMIN_DSN="$2"; shift 2 ;;
        --database)  DBNAME="$2";    shift 2 ;;
        --domain)    DOMAIN="$2";    shift 2 ;;
        --app-password) APP_PASS="$2"; shift 2 ;;
        --dry-run)   DRY_RUN=1;      shift ;;
        -h|--help)   sed -n '2,25p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

die() { echo "provision: $*" >&2; exit 1; }
say() { printf '\n== %s\n' "$*"; }

[[ -n "$ADMIN_DSN" ]] || die "--admin-dsn is required (a role that can CREATE DATABASE)"
[[ -n "$DOMAIN"    ]] || die "--domain is required; it goes in the opt-out links recipients click"
command -v psql >/dev/null || die "psql not found"

BASE="${ADMIN_DSN%/*}"
OWNER_DSN="$BASE/$DBNAME"

# ---------------------------------------------------------------- 1. database
say "database $DBNAME"
if psql -tA -d "$ADMIN_DSN" -c \
     "SELECT 1 FROM pg_database WHERE datname = '$DBNAME'" | grep -q 1; then
    echo "   already exists"
else
    [[ $DRY_RUN -eq 1 ]] || psql -q -v ON_ERROR_STOP=1 -d "$ADMIN_DSN" \
        -c "CREATE DATABASE \"$DBNAME\""
    echo "   created"
fi

# ---------------------------------------------------------------- 2. schema
#
# Applied by the owner, in directory order. The directory IS the list: a
# hand-written order drifted out of step with it in four places once already,
# and three of them were wrong.
say "migrations"
existing=$(psql -tA -d "$OWNER_DSN" -c \
    "SELECT count(*) FROM information_schema.tables
     WHERE table_schema = 'public' AND table_name = 'app_user'" 2>/dev/null || echo 0)
if [[ "$existing" == "1" ]]; then
    have=$(psql -tA -d "$OWNER_DSN" -c \
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
    want=$(ls migrations/[0-9]*.sql | wc -l | tr -d ' ')
    echo "   schema already present ($have tables); not re-applying"
    echo "   there are $want migrations on disk. If any are new to this"
    echo "   database, read them and apply them yourself:"
    echo "     psql -v ON_ERROR_STOP=1 -d \"\$OWNER_DSN\" -f migrations/00NN_....sql"
    echo "   Nothing here tracks which have been applied, and an unattended"
    echo "   runner would remove the moment where somebody notices."
    SEEDED=1
else
    n=0
    for f in migrations/[0-9]*.sql; do
        [[ $DRY_RUN -eq 1 ]] || psql -q -v ON_ERROR_STOP=1 -d "$OWNER_DSN" -f "$f"
        n=$((n + 1))
    done
    echo "   applied $n"
    SEEDED=0
fi

# ---------------------------------------------------------------- 3. seeds
#
# Only the two a real database needs. 002_buyer_mandates is twenty-three
# synthetic mandates and dev_only_users is four accounts on a domain Crown does
# not own — applying either here would put demonstration data in a system that
# contacts real people, and NOTHING_SYNTHETIC_HAS_LEFT exists because that is a
# real failure mode rather than a hypothetical one.
say "seeds (configuration and the data rights register only)"
if [[ "${SEEDED:-0}" == "1" ]]; then
    echo "   skipped; the schema was already here and so are its seeds"
else
    for f in seeds/001_config.sql seeds/003_candidate_sources.sql; do
        [[ $DRY_RUN -eq 1 ]] || psql -q -v ON_ERROR_STOP=1 -d "$OWNER_DSN" -f "$f"
        echo "   $f"
    done
fi

# ---------------------------------------------------------------- 4. the role
#
# THE MOST IMPORTANT STEP IN THIS FILE.
#
# Row-level security is the authorisation model: twenty tables, and every policy
# assumes the connection is subject to them. A superuser is exempt from all of
# it, FORCE included, and BYPASSRLS defeats FORCE specifically. Managed Postgres
# hands you an administrative user, and it is the obvious thing to put in
# CROWN_DSN — at which point the application works perfectly and answers every
# query as though no policy existed.
#
# 0002 creates crown_app NOSUPERUSER. This gives it a password, makes sure it
# cannot bypass, and confirms it owns nothing.
say "application role"
# If an env file is already here, its DSN holds the password the running service
# is using. Generating a new one and leaving that file alone would rotate the
# database password out from under a working deployment and the only symptom
# would be authentication failures after the next restart — so reuse it.
if [[ -z "$APP_PASS" && -f "$ENVFILE" ]]; then
    APP_PASS="$(sed -n 's|^CROWN_DSN=.*//crown_app:\([^@]*\)@.*|\1|p' "$ENVFILE")"
    [[ -n "$APP_PASS" ]] && echo "   reusing the password in $ENVFILE"
fi
if [[ -z "$APP_PASS" ]]; then
    APP_PASS="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
    echo "   generated a password for crown_app"
fi
if [[ $DRY_RUN -eq 0 ]]; then
    psql -q -v ON_ERROR_STOP=1 -d "$OWNER_DSN" <<PSQL
ALTER ROLE crown_app WITH LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
     PASSWORD '$APP_PASS';
PSQL
    owned=$(psql -tA -d "$OWNER_DSN" -c \
      "SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner
       WHERE r.rolname = 'crown_app' AND c.relkind = 'r'")
    [[ "$owned" == "0" ]] || die "crown_app owns $owned table(s); row-level security does not constrain an owner"
    echo "   crown_app: no superuser, no bypass, owns nothing"
fi
APP_DSN="${BASE%%://*}://crown_app:$APP_PASS@${BASE#*@}/$DBNAME"

# ---------------------------------------------------------------- 5. secrets
#
# Two, and separately, because they rotate on different clocks. s18 gives an
# unsubscribe link at least 30 days of life, so rotating the cookie secret must
# not be able to kill one.
say "secrets"
if [[ -f "$ENVFILE" ]]; then
    echo "   $ENVFILE exists, leaving it alone"
else
    if [[ $DRY_RUN -eq 0 ]]; then
        mkdir -p "$(dirname "$ENVFILE")"
        umask 077
        cat > "$ENVFILE" <<ENV
# Written by deploy/provision.sh. Mode 0600 — it holds the database password
# and the secret that signs every opt-out link.
CROWN_DSN=$APP_DSN
CROWN_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
CROWN_OPTOUT_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
CROWN_OPTOUT_SECRET_PREVIOUS=
CROWN_BASE_URL=https://$DOMAIN
ENV
        chmod 600 "$ENVFILE"
    fi
    echo "   wrote $ENVFILE, mode 0600"
fi

# ---------------------------------------------------------------- 6. the gate
#
# Read as crown_app, not as the owner. The gate is a set of queries, so a
# connection exempt from the policies reads it clean and reports itself ready —
# which is the one thing a provisioning script must not do.
say "readiness"
if [[ $DRY_RUN -eq 1 ]]; then
    echo "   skipped (dry run)"
    exit 0
fi

set +e
CROWN_DSN="$APP_DSN" \
CROWN_SECRET="$(grep '^CROWN_SECRET=' "$ENVFILE" | cut -d= -f2-)" \
CROWN_OPTOUT_SECRET="$(grep '^CROWN_OPTOUT_SECRET=' "$ENVFILE" | cut -d= -f2-)" \
    python3 scripts/readiness.py
gate=$?
set -e

cat <<'NEXT'

== what is left, and why this script cannot do it

  A password for a human.  python scripts/set_password.py you@example.com
                           Interactive on purpose: a credential this script
                           generated would be a credential in a log.

  Real evidence.           python -m ingest.cli --lga Wyndham --verify
                           Needs the Victorian planning hosts reachable. If they
                           are not, tools/bookmarklet.html captures a page in a
                           browser instead and captures/ explains the rest.

  A published policy.      docs/compliance/ holds four documents, none reviewed
                           by a lawyer, and seven [DECIDE] marks remain. The
                           privacy policy must be published BEFORE collection
                           begins, not after.

NEXT

if [[ $gate -ne 0 ]]; then
    echo "provision: the readiness gate is not green, so this is not ready to launch." >&2
    echo "           Nothing above lied to you; that is what the exit code is for." >&2
    exit "$gate"
fi
echo "provision: gate green."
