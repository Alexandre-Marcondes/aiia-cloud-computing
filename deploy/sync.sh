#!/usr/bin/env bash
#
# Push the local checkout to the Azure VM (Part 2).
#
# Code goes to the VM checkout; with --web the static frontend is also published
# to Apache's document root. Only runtime source is sent (src/, web/, deploy/,
# pyproject.toml): docs, tests, scripts, and markdown are skipped, as is
# machine-local state (venv, .git, caches, weight files). Excluded paths are
# protected from --delete, and the VM builds its own venv once.
#
# Usage:
#   deploy/sync.sh              sync the code to the VM
#   deploy/sync.sh --web        also publish web/ to /var/www/html
#   deploy/sync.sh --dry-run    show what would change, copy nothing
#   deploy/sync.sh --help
#
# VM_HOST / VM_USER / VM_KEY / VM_DIR are required: they come from the repo-root
# .env (see .env.example) or the environment, e.g.:
#   VM_HOST=1.2.3.4 VM_USER=ubuntu VM_KEY=~/.ssh/other.pem deploy/sync.sh
set -euo pipefail

# shellcheck source=deploy/_env.sh
. "$(dirname "${BASH_SOURCE[0]}")/_env.sh"
WEB_ROOT="${WEB_ROOT:-/var/www/html}"
SSH_OPTS=(-i "$VM_KEY")

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

DO_WEB=0
DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --web) DO_WEB=1 ;;
        --dry-run | -n) DRY_RUN=1 ;;
        --help | -h)
            sed -n '2,17p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg" >&2
            exit 2
            ;;
    esac
done

# Required from .env / the environment (see .env.example).
require_var VM_HOST VM_USER VM_KEY VM_DIR

RSYNC_OPTS=(-az --info=progress2)
EXCLUDES=(
    # Machine-/build-local: owned by the VM or derived on the fly.
    --exclude=.git
    --exclude=venv
    --exclude=data
    --exclude=models
    --exclude=__pycache__
    --exclude=.pytest_cache
    --exclude=.ruff_cache
    --exclude='*.egg-info'
    --exclude='*.pt'
    # The machine-local configuration: the VM's own .env (if any) is not the
    # local one, and --delete must never remove or overwrite it.
    --exclude=.env
    # Docs and dev-only files: not needed to run the receiver on the VM.
    --exclude='*.md'
    --exclude=docs
    --exclude=tests
    --exclude=scripts
    --exclude=.pre-commit-config.yaml
    --exclude=.gitignore
)
# The receiver writes these into the docroot (database.csv, processed_frame.jpg,
# plot.png, processing.csv, and per-camera frames under frames/); --delete must
# not remove them. Markdown (e.g. web/AGENTS.md) is dev-only and not served.
WEB_EXCLUDES=(
    --exclude=database.csv
    --exclude=processed_frame.jpg
    --exclude=plot.png
    --exclude=processing.csv
    --exclude=frames/
    --exclude='*.md'
)
[ "$DRY_RUN" = 1 ] && RSYNC_OPTS+=(--dry-run)

echo ">> code  ${REPO_ROOT}/ -> ${VM_USER}@${VM_HOST}:${VM_DIR}/"
rsync "${RSYNC_OPTS[@]}" --delete -e "ssh ${SSH_OPTS[*]}" "${EXCLUDES[@]}" \
    "${REPO_ROOT}/" "${VM_USER}@${VM_HOST}:${VM_DIR}/"

if [ "$DO_WEB" = 1 ]; then
    echo ">> web   ${REPO_ROOT}/web/ -> ${VM_USER}@${VM_HOST}:${WEB_ROOT}/"
    rsync "${RSYNC_OPTS[@]}" --delete -e "ssh ${SSH_OPTS[*]}" \
        --rsync-path="sudo rsync" "${WEB_EXCLUDES[@]}" \
        "${REPO_ROOT}/web/" "${VM_USER}@${VM_HOST}:${WEB_ROOT}/"
fi

echo ">> done"
