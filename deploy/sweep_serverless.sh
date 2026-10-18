#!/usr/bin/env bash
#
# Sweep the multi-camera fleet against the Part 3 serverless pipeline (Task 4.3).
#
# For each camera count N in --cameras, the sender uploads to the `raw` container
# for --seconds, then measure_part3.sh collects the server-side telemetry for the
# window (--minutes, default ceil(seconds / 60)). Both are captured per N.
#
#   bash deploy/sweep_serverless.sh                           # defaults
#   bash deploy/sweep_serverless.sh --cameras "1 2 4 8 16 32" --seconds 60
#   bash deploy/sweep_serverless.sh --dry-run                 # print the plan
#
# The only az calls made are read-only (connection string + metric queries); the
# frames the pipeline consumes are the run's own uploads. Delete raw/*,
# $web/database.csv and $web/processing.csv before each N so the window is
# unambiguous, then download $web/processing.csv to data/sweeps/serverless-N-processing.csv
# after the run as the per-frame response-time evidence. Cost is read from Portal
# (see docs/performance.md).
#
# Required (from .env or the environment): STORAGE, RG.
# Overridable: RAW_CONTAINER, DATA_STORAGE, VENV, SOURCE, OUT.
set -euo pipefail

# shellcheck source=deploy/_env.sh
. "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

RAW_CONTAINER="${RAW_CONTAINER:-raw}"
VENV="${VENV:-$REPO_ROOT/venv}"
SOURCE="${SOURCE:-data/people_walking.mp4}"
OUT="${OUT:-data/sweeps}"

CAMERAS="1 2 4 8 16 32"
INTERVAL=5
WINDOW=60
MINUTES=""
COOLDOWN=0
SETTLE=60
RESET=1
DRY_RUN=0

usage() { sed -n '2,/^$/p' "$0"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --cameras) CAMERAS="$2"; shift 2 ;;
        --interval) INTERVAL="$2"; shift 2 ;;
        --seconds) WINDOW="$2"; shift 2 ;;
        --raw-container) RAW_CONTAINER="$2"; shift 2 ;;
        --storage) STORAGE="$2"; shift 2 ;;
        --rg) RG="$2"; shift 2 ;;
        --minutes) MINUTES="$2"; shift 2 ;;
        --cooldown) COOLDOWN="$2"; shift 2 ;;
        --settle) SETTLE="$2"; shift 2 ;;
        --no-reset) RESET=0; shift ;;
        --out) OUT="$2"; shift 2 ;;
        --dry-run | -n) DRY_RUN=1; shift ;;
        --help | -h) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

# Required from .env / the environment (see .env.example).
require_var STORAGE RG

# measure_part3 window defaults to cover run + ingestion settle, at least 2 min.
if [ -z "$MINUTES" ]; then
    MINUTES=$(awk -v s="$((WINDOW + SETTLE))" 'BEGIN { printf "%d", (s + 59) / 60 }')
    [ "$MINUTES" -lt 2 ] && MINUTES=2
fi

# Resolve the connection string exactly like stream_serverless.sh (read-only);
# never in --dry-run.
if [ -z "${DATA_STORAGE:-}" ] && [ "$DRY_RUN" = 0 ]; then
    echo ">> resolving connection string for '${STORAGE}' (read-only)"
    DATA_STORAGE=$(az storage account show-connection-string -n "$STORAGE" -g "$RG" \
        --query connectionString -o tsv)
fi
if [ -z "${DATA_STORAGE:-}" ]; then
    CONN_NOTE='from $DATA_STORAGE or az storage account show-connection-string (read-only)'
else
    CONN_NOTE='from $DATA_STORAGE (key not shown)'
fi

# Delete the previous window's consumed input and output so each N is isolated.
reset_window() {
    az storage blob delete-batch --account-name "$STORAGE" --source "$RAW_CONTAINER" \
        --auth-mode key -o none 2>/dev/null || true
    az storage blob delete --account-name "$STORAGE" --container-name '$web' \
        --name database.csv --auth-mode key -o none 2>/dev/null || true
    az storage blob delete --account-name "$STORAGE" --container-name '$web' \
        --name processing.csv --auth-mode key -o none 2>/dev/null || true
}

echo ">> sweep (Part 4.3): N in ${CAMERAS// /,}  interval=${INTERVAL}s  window=${WINDOW}s  cooldown=${COOLDOWN}s  -> ${STORAGE}/${RAW_CONTAINER}"

FAILED=0
for N in $CAMERAS; do
    FILE="$OUT/serverless-$N.txt"

    if [ "$DRY_RUN" = 1 ]; then
        echo
        echo "== N = ${N} =="
        printf '%s\n' \
            "${VENV}/bin/python src/local_stream.py --cameras ${N} --interval ${INTERVAL}" \
            "             --seconds ${WINDOW} --raw-container ${RAW_CONTAINER} --no-display" \
            "             --blob-connection-string <connection string>"
        echo "   sleep ${SETTLE}s (metric ingestion), then: bash deploy/measure_part3.sh --minutes ${MINUTES}"
        echo "   download \$web/processing.csv -> ${OUT}/serverless-${N}-processing.csv (missing tolerated)"
        echo "   (conn: ${CONN_NOTE})"
        [ "$RESET" = 1 ] && echo "   reset ${RAW_CONTAINER}/* and \$web/database.csv + \$web/processing.csv (azure deletes)"
        [ "$COOLDOWN" != 0 ] && echo "   sleep ${COOLDOWN}s"
        echo "   tee both streams -> ${FILE}"
        continue
    fi

    mkdir -p "$OUT"
    start=$(date +%s)
    echo
    echo ">> N=${N}: streaming ${WINDOW}s to ${STORAGE}/${RAW_CONTAINER}, then collecting metrics (${MINUTES}m)"
    if [ "$RESET" = 1 ]; then
        echo "   resetting ${RAW_CONTAINER}/* and \$web/database.csv + \$web/processing.csv"
        reset_window
    fi
    set +e
    "${VENV}/bin/python" src/local_stream.py \
        --cameras "$N" --interval "$INTERVAL" --seconds "$WINDOW" \
        --raw-container "$RAW_CONTAINER" --blob-connection-string "$DATA_STORAGE" \
        --no-display 2>&1 | tee "$FILE"
    FLEET_RC=${PIPESTATUS[0]}
    echo ">> settle ${SETTLE}s for Azure Monitor ingestion, then collect metrics"
    sleep "$SETTLE"
    bash deploy/measure_part3.sh --rg "$RG" --storage "$STORAGE" --minutes "$MINUTES" \
        2>&1 | tee -a "$FILE"
    MEASURE_RC=${PIPESTATUS[0]}
    set -e
    az storage blob download --account-name "$STORAGE" --container-name '$web' \
        --name processing.csv --file "$OUT/serverless-${N}-processing.csv" \
        --auth-mode key -o none 2>/dev/null || echo "   (no processing.csv captured)"
    wall=$(( $(date +%s) - start ))

    if [ "$FLEET_RC" = 0 ] && [ "$MEASURE_RC" = 0 ]; then
        echo "serverless-${N} : N=${N} x ${WINDOW}s + ${MINUTES}m metrics in ${wall}s wall - ok (capture -> ${FILE})"
    else
        echo "serverless-${N} : N=${N} - fleet rc=${FLEET_RC}, metrics rc=${MEASURE_RC} (see ${FILE})"
        FAILED=1
    fi

    if [ "$COOLDOWN" != 0 ]; then
        echo ">> cooldown ${COOLDOWN}s"
        sleep "$COOLDOWN"
    fi
done

[ "$FAILED" = 0 ]
