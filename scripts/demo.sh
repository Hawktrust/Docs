#!/usr/bin/env bash
# Build a throwaway demo database and run the app against it.
#
# The demo database carries DEMO_SYNTHETIC evidence so the loop can be walked
# without live ingestion. Do not point this at a real database.
set -euo pipefail

DB="${CROWN_DEMO_DB:-crown_demo}"
ADMIN="${CROWN_ADMIN_DSN:-postgresql:///postgres}"
BASE="${ADMIN%/*}"
# The DSN of the demo database this script just built. It was used twice below
# and never assigned, so with set -u the script aborted on "DEMO_DSN: unbound
# variable" immediately after applying the schema — the README's own "see the
# loop" instruction got as far as an empty database and then stopped. Exported
# because the python3 block reads it from the environment.
export DEMO_DSN="$BASE/$DB"

psql -q -d "$ADMIN" -c "DROP DATABASE IF EXISTS $DB WITH (FORCE)"
psql -q -d "$ADMIN" -c "CREATE DATABASE $DB"

# Every migration in the directory, then the seeds, in order. Discovered rather
# than listed: the same list hand-maintained in CI had already drifted, and a
# demo built from a partial schema fails in ways that look like application bugs.
for f in migrations/[0-9]*.sql \
         seeds/001_config.sql \
         seeds/dev_only_users.sql \
         seeds/002_buyer_mandates.sql \
         seeds/003_candidate_sources.sql \
         seeds/dev_only_demo_evidence.sql; do
    psql -q -v ON_ERROR_STOP=1 -d "$BASE/$DB" -f "$f"
    echo "applied $f"
done

python3 -m ingest.cli --lga Wyndham --leads seeds/relay_leads.json --dsn "$DEMO_DSN" || true

python3 -c "
import os, psycopg
from crown import opportunity, matching
conn = psycopg.connect(os.environ['DEMO_DSN'])
owner = conn.execute(\"SELECT id FROM app_user WHERE email='analyst@crown.local'\").fetchone()[0]
for change in opportunity.refresh(conn, owner):
    matching.rank(conn, change.opportunity_id, actor_user_id=owner)
    print(f'  {change.lga}/{change.geography_label}: {change.stage}')
conn.commit()
" 

echo
echo "Demo database ready. Run the app with:"
echo "  CROWN_DSN='$BASE/$DB' CROWN_SECRET=dev CROWN_INSECURE_COOKIES=1 \\"
echo "    flask --app crown.web:create_app run"
echo "  (CROWN_INSECURE_COOKIES=1 only because the dev server is http; never set it in production)"
echo "Set a password first (seeded accounts have none, so nobody can be them):"
echo "  CROWN_DSN='$BASE/$DB' python3 scripts/set_password.py hawk@crown.local"
echo "Then sign in as hawk@crown.local, analyst@crown.local, compliance@crown.local or agent@crown.local"
