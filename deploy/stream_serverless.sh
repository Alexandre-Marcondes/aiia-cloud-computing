#!/usr/bin/env bash
#
# Stream local frames to the Part 3 serverless pipeline (Task 3.2 sender).
#
# Samples the source video in real time every --interval seconds (default the
# test clip, 0.5 s) and uploads each frame to the private `raw` container; the
# blob trigger then processes it. Loops the clip until stopped, so it is a
# continuous "camera". Stop with Ctrl-C.
#
#   bash deploy/stream_serverless.sh                          # continuous, 0.5 s
#   bash deploy/stream_serverless.sh --fast --max-samples 20  # quick burst
#   bash deploy/stream_serverless.sh --cameras 3              # 3 pseudo-cameras
#   bash deploy/stream_serverless.sh --cameras 3 --phase-offset 5   # ...5 s apart in the clip
#
# With --cameras N > 1 one local clip drives N pseudo-cameras (`cam-1`..`cam-N`,
# or `<camera-id>-i` when --camera-id is given); --max-samples then applies per
# camera. Multi-camera needs an upload target (always the blob case here) and a
# local video, so it is incompatible with --fast. --phase-offset S makes each
# successive camera sample the clip S seconds behind the previous, so the
# cameras show different points in time instead of the same frame.
#
# The storage connection string is taken from $DATA_STORAGE if set, otherwise
# queried from Azure (read-only). Note: at 0.5 s this is ~2 Vision calls/s, so
# don't leave it running longer than the measurement window.
#
# Required (from .env or the environment): STORAGE, RG.
# Overridable: RAW_CONTAINER, VENV.
set -euo pipefail

# shellcheck source=deploy/_env.sh
. "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

RAW_CONTAINER="${RAW_CONTAINER:-raw}"
VENV="${VENV:-$REPO_ROOT/venv}"

SOURCE="data/people_walking.mp4"
INTERVAL=0.5
CAMERA=""
CAMERAS=1
PHASE=0
FAST=0
MAX_SAMPLES=0
SHOW_DISPLAY=0

while [ $# -gt 0 ]; do
    case "$1" in
        --source) SOURCE="$2"; shift 2 ;;
        --interval) INTERVAL="$2"; shift 2 ;;
        --camera-id) CAMERA="$2"; shift 2 ;;
        --cameras) CAMERAS="$2"; shift 2 ;;
        --phase-offset) PHASE="$2"; shift 2 ;;
        --max-samples) MAX_SAMPLES="$2"; shift 2 ;;
        --raw-container) RAW_CONTAINER="$2"; shift 2 ;;
        --storage) STORAGE="$2"; shift 2 ;;
        --rg) RG="$2"; shift 2 ;;
        --fast) FAST=1; shift ;;
        --display) SHOW_DISPLAY=1; shift ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

# Required from .env / the environment (see .env.example).
require_var STORAGE RG

if [ -z "${DATA_STORAGE:-}" ]; then
    echo ">> resolving connection string for '${STORAGE}' (read-only)"
    DATA_STORAGE=$(az storage account show-connection-string -n "$STORAGE" -g "$RG" \
        --query connectionString -o tsv)
fi

ARGS=(
    --source "$SOURCE"
    --interval "$INTERVAL"
    --cameras "$CAMERAS"
    --raw-container "$RAW_CONTAINER"
    --blob-connection-string "$DATA_STORAGE"
)
if [ -n "$CAMERA" ]; then
    ARGS+=(--camera-id "$CAMERA")
fi
if [ "$PHASE" != 0 ]; then
    ARGS+=(--phase-offset "$PHASE")
fi
if [ "$FAST" = 1 ]; then
    ARGS+=(--fast)
fi
if [ "$MAX_SAMPLES" != 0 ]; then
    ARGS+=(--max-samples "$MAX_SAMPLES")
fi
if [ "$SHOW_DISPLAY" != 1 ]; then
    ARGS+=(--no-display)
fi

echo ">> streaming '${SOURCE}' every ${INTERVAL}s -> ${STORAGE}/${RAW_CONTAINER} (camera '${CAMERA:-cam}')"
echo ">> stop with Ctrl-C"
"${VENV}/bin/python" src/local_stream.py "${ARGS[@]}"
