#!/usr/bin/env bash
# Import every committed capture bundle.
#
#   CROWN_DSN=... ./scripts/import_captures.sh you@crownrea.com.au
#
# Safe to re-run: the importer deduplicates on the page hash, so a second run
# reports the records as already held rather than creating them twice.
set -euo pipefail

OPERATOR="${1:-}"
if [[ -z "$OPERATOR" ]]; then
    echo "usage: $0 you@crownrea.com.au" >&2
    echo >&2
    echo "A capture is a person saying they opened the page and checked it," >&2
    echo "so the importer needs to know which person." >&2
    exit 2
fi

shopt -s nullglob
BUNDLES=(captures/*.json)
if [[ ${#BUNDLES[@]} -eq 0 ]]; then
    echo "no bundles in captures/ — see captures/README.md" >&2
    exit 1
fi

echo "importing ${#BUNDLES[@]} bundle(s) as $OPERATOR"
python3 -m ingest.cli --capture "${BUNDLES[@]}" --as "$OPERATOR"
