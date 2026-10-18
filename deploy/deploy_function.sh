#!/usr/bin/env bash
#
# Build and deploy the Part 3 serverless Function App (no VS Code needed).
#
# Assembles build/function/ with deploy/build_function.sh, zips it (excluding the
# local-only .vscode/.funcignore), and pushes it to the Function App with
# `az functionapp deployment source config-zip --build-remote true`. Azure then
# runs the Oryx build (`pip install -r requirements.txt`) on the platform.
#
#   bash deploy/deploy_function.sh
#   bash deploy/deploy_function.sh --dry-run     # build + zip only, print the plan
#
# This changes the running app's code (a brief restart); no infrastructure and no
# cost beyond the deploy. Required (from .env or the environment): RG, FUNC.
# Overridable: BUILD_DIR, ZIP.
set -euo pipefail

# shellcheck source=deploy/_env.sh
. "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BUILD_DIR="${BUILD_DIR:-build/function}"
ZIP="${ZIP:-build/function.zip}"
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
require_var RG FUNC

echo ">> assembling ${BUILD_DIR}/"
bash deploy/build_function.sh >/dev/null

ZIP_ABS="${REPO_ROOT}/${ZIP}"
rm -f "$ZIP_ABS"
( cd "$BUILD_DIR" && zip -qr "$ZIP_ABS" . -x '.vscode/*' -x '.funcignore' )
echo ">> packaged ${ZIP} ($(du -h "$ZIP_ABS" | cut -f1))"

if [ "$DRY_RUN" = 1 ]; then
    echo ">> dry-run: would deploy to ${FUNC} (${RG}) with --build-remote true"
    exit 0
fi

echo ">> deploying to ${FUNC} (${RG}) with a remote build ..."
az functionapp deployment source config-zip -g "$RG" -n "$FUNC" --src "$ZIP_ABS" \
    --build-remote true -o tsv --query provisioningState
echo ">> done; the static site is served from the \$web container"
