#!/usr/bin/env bash
# Back Crown up, and prove the backup restores.
#
# An untested backup is a belief. --verify-restore loads the dump into a
# scratch database and compares row counts on the tables that matter; it exits
# non-zero if they disagree, which is the only way to find out before you need
# to know.
#
#   ./backup.sh                     dump to $CROWN_BACKUP_DIR
#   ./backup.sh --verify-restore    dump, restore to a scratch db, compare, drop
set -euo pipefail

DIR="${CROWN_BACKUP_DIR:-/var/backups/crown}"
KEEP_DAYS="${CROWN_BACKUP_KEEP_DAYS:-30}"
DSN="${CROWN_BACKUP_DSN:-${CROWN_DSN:?set CROWN_DSN or CROWN_BACKUP_DSN}}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$DIR/crown-$STAMP.dump"

# Tables whose row counts a restore must reproduce. Not all of them — these are
# the ones whose loss would be unrecoverable rather than merely annoying.
WITNESSES=(audit_event contact_suppression contact_consent outbound_artifact
           evidence_record app_user outbound_identity)

mkdir -p "$DIR"
umask 077          # a database dump is the most sensitive file on the machine

echo "dumping to $OUT"
pg_dump --format=custom --no-owner --file="$OUT" "$DSN"
echo "dumped $(du -h "$OUT" | cut -f1)"

if [[ "${1:-}" == "--verify-restore" ]]; then
    SCRATCH="crown_restore_check_$STAMP"
    ADMIN="${CROWN_ADMIN_DSN:-${DSN%/*}/postgres}"

    cleanup() { psql -q -d "$ADMIN" -c "DROP DATABASE IF EXISTS \"$SCRATCH\" WITH (FORCE)" >/dev/null 2>&1 || true; }
    trap cleanup EXIT

    echo "restoring into $SCRATCH"
    psql -q -d "$ADMIN" -c "CREATE DATABASE \"$SCRATCH\""
    pg_restore --no-owner --dbname="${DSN%/*}/$SCRATCH" "$OUT" >/dev/null

    failed=0
    for t in "${WITNESSES[@]}"; do
        before=$(psql -tA -d "$DSN" -c "SELECT count(*) FROM $t" 2>/dev/null || echo skip)
        after=$(psql -tA -d "${DSN%/*}/$SCRATCH" -c "SELECT count(*) FROM $t" 2>/dev/null || echo skip)
        [[ "$before" == skip ]] && continue
        if [[ "$before" != "$after" ]]; then
            echo "MISMATCH $t: live $before, restored $after" >&2
            failed=1
        else
            printf '  %-22s %s rows\n' "$t" "$after"
        fi
    done
    [[ $failed -eq 0 ]] || { echo "restore did not reproduce the data" >&2; exit 1; }
    echo "restore verified"
fi

# Retention on the dumps themselves. They contain every name Crown holds, so
# keeping them forever would quietly defeat the retention rules in the database
# they came from.
find "$DIR" -name 'crown-*.dump' -mtime "+$KEEP_DAYS" -print -delete
