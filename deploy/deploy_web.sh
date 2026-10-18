#!/usr/bin/env bash
#
# Publish the static frontend (web/) to the Part 3 Azure Storage `$web`
# container that serves the static website.
#
# This is the `$web` analogue of `sync.sh --web`: where that rsyncs web/ to the
# VM's Apache document root, this uploads the static site files to Azure
# Storage. Each file is uploaded explicitly (never `upload-batch`, never
# `--delete`), so the pipeline's runtime blobs in `$web` — database.csv,
# processing.csv, processed_frame.jpg, frames/* — are left untouched.
#
#   bash deploy/deploy_web.sh
#   bash deploy/deploy_web.sh --dry-run     # print the uploads, run nothing
#
# Changes only these three blobs; no infrastructure and ~zero cost.
# Required (from .env or the environment): STORAGE, RG.
# Overridable: WEB_CONTAINER, SRC.

set -euo pipefail

# shellcheck source=deploy/_env.sh
. "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

WEB_CONTAINER="${WEB_CONTAINER:-\$web}"
SRC="${SRC:-$REPO_ROOT/web}"
DRY_RUN=0

usage() { sed -n '2,/^$/p' "$0"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run | -n) DRY_RUN=1; shift ;;
        --help | -h) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

# Required from .env / the environment (see .env.example).
require_var STORAGE RG

FILES=(index.html style.css script.js not_found.html)

echo ">> publishing ${SRC}/ -> ${STORAGE}:\$web (${WEB_CONTAINER})"

for file in "${FILES[@]}"; do
    cmd=(az storage blob upload --account-name "$STORAGE" --container-name "$WEB_CONTAINER"
        --name "$file" --file "$SRC/$file" --overwrite --auth-mode key)
    if [ "$DRY_RUN" = 1 ]; then
        echo "   ${cmd[*]}"
    else
        "${cmd[@]}" -o none
        echo "   ${file} -> uploaded"
    fi
done

if [ "$DRY_RUN" = 1 ]; then
    echo ">> dry-run: no uploads performed"
else
    echo ">> done"
fi
