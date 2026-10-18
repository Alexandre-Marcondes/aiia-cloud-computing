#!/usr/bin/env bash
#
# Stream local frames to the Part 2 VM receiver (the VM analogue of
# stream_serverless.sh).
#
# Samples the source video in real time every --interval seconds and uploads
# each frame to the receiver instead of processing locally. The receiver
# listens on :8000, which the VM's NSG does not expose, so this opens an SSH
# local-forward (localhost:LOCAL_PORT -> the VM's 127.0.0.1:8000), streams until
# Ctrl-C, then closes the tunnel. Pass --url to target a different receiver (a
# direct public IP once NSG 8000 is open) or --no-tunnel to reuse an existing
# forward.
#
#   bash deploy/stream_vm.sh                            # continuous, 5 s
#   bash deploy/stream_vm.sh --interval 0.5             # faster
#   bash deploy/stream_vm.sh --fast --max-samples 5     # quick burst
#   bash deploy/stream_vm.sh --cameras 3                # 3 pseudo-cameras
#   bash deploy/stream_vm.sh --cameras 3 --phase-offset 5   # ...5 s apart in the clip
#   bash deploy/stream_vm.sh --no-tunnel                # reuse an existing tunnel
#   bash deploy/stream_vm.sh --url "http://<vm-public-ip>:8000"   # direct (NSG 8000 open)
#
# The receiver must already run on the VM (deploy/sls-receiver.service, installed
# by deploy/setup_vm.sh).
# Required (from .env or the environment): VM_HOST, VM_USER, VM_KEY.
# Overridable: LOCAL_PORT, VENV (also --vm-host/--vm-user/--vm-key).
set -euo pipefail

# shellcheck source=deploy/_env.sh
. "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

LOCAL_PORT="${LOCAL_PORT:-8000}"
VENV="${VENV:-$REPO_ROOT/venv}"

SOURCE="data/people_walking.mp4"
INTERVAL=5
CAMERA=""
CAMERAS=1
PHASE=0
FAST=0
MAX_SAMPLES=0
SHOW_DISPLAY=0
URL=""
TUNNEL=1
DRY_RUN=0

usage() { sed -n '2,/^$/p' "$0"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --source) SOURCE="$2"; shift 2 ;;
        --interval) INTERVAL="$2"; shift 2 ;;
        --camera-id) CAMERA="$2"; shift 2 ;;
        --cameras) CAMERAS="$2"; shift 2 ;;
        --phase-offset) PHASE="$2"; shift 2 ;;
        --max-samples) MAX_SAMPLES="$2"; shift 2 ;;
        --fast) FAST=1; shift ;;
        --display) SHOW_DISPLAY=1; shift ;;
        --url) URL="$2"; shift 2 ;;
        --no-tunnel) TUNNEL=0; shift ;;
        --local-port) LOCAL_PORT="$2"; shift 2 ;;
        --vm-host) VM_HOST="$2"; shift 2 ;;
        --vm-user) VM_USER="$2"; shift 2 ;;
        --vm-key) VM_KEY="$2"; shift 2 ;;
        --dry-run | -n) DRY_RUN=1; shift ;;
        --help | -h) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

# Required from .env / the environment (see .env.example).
require_var VM_HOST VM_USER VM_KEY

# A caller-supplied --url (public IP or an existing forward) skips the tunnel;
# otherwise default to the local end of the forward this script opens.
if [ -n "$URL" ]; then
    TUNNEL=0
else
    URL="http://127.0.0.1:${LOCAL_PORT}"
fi

ARGS=(
    --source "$SOURCE"
    --interval "$INTERVAL"
    --cameras "$CAMERAS"
    --cloud-url "$URL"
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

if [ "$DRY_RUN" = 1 ]; then
    if [ "$TUNNEL" = 1 ]; then
        echo ">> ssh -i ${VM_KEY} -N -L ${LOCAL_PORT}:127.0.0.1:8000 ${VM_USER}@${VM_HOST} &"
    fi
    echo "   ${VENV}/bin/python src/local_stream.py ${ARGS[*]}"
    exit 0
fi

# Close the tunnel whenever this script exits, however it exits.
TUNNEL_PID=""
cleanup() {
    if [ -n "$TUNNEL_PID" ]; then
        kill "$TUNNEL_PID" 2>/dev/null || true
        wait "$TUNNEL_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

if [ "$TUNNEL" = 1 ]; then
    # A forward may already be open on LOCAL_PORT (e.g. a manually-started
    # tunnel); reuse it rather than failing to bind a second one.
    if curl -s -m 3 "${URL%/}/health" >/dev/null 2>&1; then
        echo ">> reusing the forward already open on 127.0.0.1:${LOCAL_PORT}"
        TUNNEL=0
    else
        echo ">> opening SSH tunnel 127.0.0.1:${LOCAL_PORT} -> ${VM_USER}@${VM_HOST}:8000"
        ssh -i "$VM_KEY" -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
            -L "${LOCAL_PORT}:127.0.0.1:8000" "${VM_USER}@${VM_HOST}" &
        TUNNEL_PID=$!
    fi
fi

HEALTH="${URL%/}/health"
for _ in $(seq 1 30); do
    if [ "$TUNNEL" = 1 ] && ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
        echo ">> tunnel exited before the receiver became reachable" >&2
        exit 1
    fi
    curl -s -m 4 "$HEALTH" >/dev/null 2>&1 && break
    sleep 1
done

echo ">> streaming '${SOURCE}' every ${INTERVAL}s -> ${URL} (camera '${CAMERA:-cam}')"
echo ">> stop with Ctrl-C"
"${VENV}/bin/python" src/local_stream.py "${ARGS[@]}"
