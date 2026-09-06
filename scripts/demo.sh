#!/usr/bin/env bash
# Build a throwaway demo database and run the app against it.
#
# The demo database carries DEMO_SYNTHETIC evidence so the loop can be walked
# without live ingestion. Do not point this at a real database.
set -euo pipefail

DB="${CROWN_DEMO_DB:-crown_demo}"
ADMIN="${CROWN_ADMIN_DSN:-postgresql:///postgres}"
BASE="${ADMIN%/*}"

psql -q -d "$ADMIN" -c "DROP DATABASE IF EXISTS $DB WITH (FORCE)"
psql -q -d "$ADMIN" -c "CREATE DATABASE $DB"

for f in migrations/0001_ticket01_thin_loop.sql \
         migrations/0002_rls_policies.sql \
         migrations/0003_retrieval_method.sql \
         migrations/0004_integrity_fixes.sql \
         seeds/001_users_and_config.sql \
         seeds/002_buyer_mandates.sql \
         seeds/dev_only_demo_evidence.sql; do
    psql -q -v ON_ERROR_STOP=1 -d "$BASE/$DB" -f "$f"
    echo "applied $f"
done

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
echo "Sign in as hawk@crown.local, analyst@crown.local, compliance@crown.local or agent@crown.local"
