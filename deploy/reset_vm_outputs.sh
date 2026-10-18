#!/usr/bin/env bash
#
# Clear the SLS receiver's runtime outputs on the Azure VM so a new streaming
# run starts from an empty document root with fresh CSV headers (Part 2/4).
#
#   bash deploy/reset_vm_outputs.sh ~/.ssh/<key>.pem <vm-ssh-user>@<vm-public-ip>
#
# Deletes database.csv, processing.csv, processed_frame.jpg and the frames/
# directory from the document root and reports the result. The receiver keeps
# running and recreates each file on the next frame (with the current schema's
# header) -- deleting processing.csv is what makes a schema change take effect.
#
# Arguments: <ssh-key-path> <user@host>. Each may be omitted when it can be
# taken from .env instead (<ssh-key-path> <- VM_KEY, <user@host> <- VM_USER@VM_HOST);
# a missing value with no .env fallback is an error.
# Overridable: WEB_ROOT (default /var/www/html).

set -euo pipefail

# shellcheck source=deploy/_env.sh
. "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

usage() { sed -n '2,/^$/p' "$0"; }

case "${1:-}" in
    -h | --help) usage; exit 0 ;;
esac

KEY="${1:-${VM_KEY:-}}"
TARGET="${2:-}"
if [ -z "$TARGET" ] && [ -n "${VM_USER:-}" ] && [ -n "${VM_HOST:-}" ]; then
    TARGET="${VM_USER}@${VM_HOST}"
fi
WEB_ROOT="${WEB_ROOT:-/var/www/html}"

if [ -z "${KEY}" ] || [ -z "${TARGET:-}" ]; then
    echo "error: expected <ssh-key-path> <user@host> (or VM_KEY / VM_USER+VM_HOST in .env)" >&2
    echo
    usage >&2
    exit 2
fi

echo ">> clearing ${WEB_ROOT} on ${TARGET}"
ssh -i "${KEY}" "${TARGET}" \
    "rm -f '${WEB_ROOT}/database.csv' '${WEB_ROOT}/processing.csv' \
        '${WEB_ROOT}/processed_frame.jpg'; \
     rm -rf '${WEB_ROOT}/frames'; \
     echo '   removed (if present): database.csv processing.csv processed_frame.jpg frames/'"
echo ">> done; the receiver will recreate them on the next frame"
