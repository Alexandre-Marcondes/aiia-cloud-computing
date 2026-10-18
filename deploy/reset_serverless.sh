#!/usr/bin/env bash
#
# Clear the Part 3 serverless pipeline's runtime output on Azure Storage so a new
# run starts from an empty site (fresh CSV headers, no stale frames). The static
# site's own files (index.html, script.js, not_found.html) are kept.
#
#   bash deploy/reset_serverless.sh
#
# Removes: `raw/*` (queued input), `$web/database.csv`, `$web/processing.csv`,
# `$web/processed_frame.jpg`, and `$web/frames/*`. These blob deletions are the
# only state change -- no infrastructure, ~zero cost.
#
# Required (from .env or the environment): STORAGE, RG.
# Overridable: WEB_CONTAINER, RAW_CONTAINER.

set -euo pipefail

# shellcheck source=deploy/_env.sh
. "$(dirname "${BASH_SOURCE[0]}")/_env.sh"
WEB_CONTAINER="${WEB_CONTAINER:-\$web}"
RAW_CONTAINER="${RAW_CONTAINER:-raw}"

usage() { sed -n '2,/^$/p' "$0"; }

case "${1:-}" in
    -h | --help) usage; exit 0 ;;
esac

# Required from .env / the environment (see .env.example).
require_var STORAGE RG

list_web() {
    az storage blob list --account-name "$STORAGE" --container-name "$WEB_CONTAINER" \
        --auth-mode key --query "[].name" -o tsv 2>/dev/null
}
count_container() {
    az storage blob list --account-name "$STORAGE" --container-name "$1" \
        --auth-mode key --query "length(@)" -o tsv 2>/dev/null
}

echo ">> clearing runtime output on ${STORAGE} (raw/* and \$web outputs)"

az storage blob delete-batch --account-name "$STORAGE" --source "$RAW_CONTAINER" \
    --auth-mode key -o none 2>/dev/null || true
echo "   ${RAW_CONTAINER}/*         -> $(count_container "$RAW_CONTAINER") blobs left"

for blob in database.csv processing.csv processed_frame.jpg; do
    az storage blob delete --account-name "$STORAGE" --container-name "$WEB_CONTAINER" \
        --name "$blob" --auth-mode key -o none 2>/dev/null || true
done
echo "   \$web runtime blobs    -> cleared (database.csv, processing.csv, processed_frame.jpg)"

az storage blob delete-batch --account-name "$STORAGE" --source "$WEB_CONTAINER" \
    --pattern 'frames/*' --auth-mode key -o none 2>/dev/null || true
echo "   \$web/frames/*         -> $(az storage blob list --account-name "$STORAGE" \
    --container-name "$WEB_CONTAINER" --prefix 'frames/' --auth-mode key \
    --query 'length(@)' -o tsv 2>/dev/null || echo 0) blobs left"

echo ">> remaining \$web blobs:"
list_web | sed 's/^/   /'
