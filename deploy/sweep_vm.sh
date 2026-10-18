#!/usr/bin/env bash
#
# Sweep the multi-camera fleet against the Part 2 VM (Task 4.2).
#
# For each camera count N in --cameras, this resets the receiver's document root,
# streams frames to the VM receiver (--url) for --seconds while measure.sh samples
# the receiver's CPU / memory / network on the VM over SSH, then captures the
# measure report, the fleet log, and the per-N telemetry (processing.csv /
# database.csv). --cooldown seconds are waited after each N so swap can drain
# between runs (the receiver saturates into swap thrash near the limit); with
# --restart the receiver is restarted before each N instead, which clears the
# backlog and releases swap for a clean, reproducible starting state.
#
#   bash deploy/sweep_vm.sh
#   bash deploy/sweep_vm.sh --cameras "4 6 8 10 12" --seconds 60 --cooldown 60
#   bash deploy/sweep_vm.sh --cameras "12 13 14" --seconds 60 --restart
#   bash deploy/sweep_vm.sh --dry-run                        # print the plan
#
# The receiver must already run on the VM (deploy/sync.sh + sls-receiver).
# Required (from .env or the environment): VM_HOST, VM_USER, VM_KEY, VM_DIR.
# Overridable: WEB_ROOT, VENV, SOURCE, OUT.
set -euo pipefail

# shellcheck source=deploy/_env.sh
. "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
WEB_ROOT="${WEB_ROOT:-/var/www/html}"
VENV="${VENV:-$REPO_ROOT/venv}"
SOURCE="${SOURCE:-data/people_walking.mp4}"
OUT="${OUT:-data/sweeps}"

CAMERAS="1 2 4 8 16 32"
INTERVAL=5
WINDOW=60
COOLDOWN=0
RESTART=0
URL=""
DRY_RUN=0

usage() { sed -n '2,/^$/p' "$0"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --cameras) CAMERAS="$2"; shift 2 ;;
        --interval) INTERVAL="$2"; shift 2 ;;
        --seconds) WINDOW="$2"; shift 2 ;;
        --cooldown) COOLDOWN="$2"; shift 2 ;;
        --restart) RESTART=1; shift ;;
        --url) URL="$2"; shift 2 ;;
        --out) OUT="$2"; shift 2 ;;
        --dry-run | -n) DRY_RUN=1; shift ;;
        --help | -h) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

# Required from .env / the environment (see .env.example).
require_var VM_HOST VM_USER VM_KEY VM_DIR
# --url retargets the receiver, otherwise it is the VM on :8000.
URL="${URL:-http://${VM_HOST}:8000}"

HEALTH="${URL%/}/health"

RESET="rm -f '${WEB_ROOT}/database.csv' '${WEB_ROOT}/processing.csv' \
    '${WEB_ROOT}/processed_frame.jpg'; rm -rf '${WEB_ROOT}/frames'"

echo ">> sweep (Part 4.2): N in ${CAMERAS// /,}  interval=${INTERVAL}s  window=${WINDOW}s  cooldown=${COOLDOWN}s  -> ${URL}"

FAILED=0
for N in $CAMERAS; do
    FILE="$OUT/vm-$N.txt"
    MEASURE="cd ${VM_DIR} && bash deploy/measure.sh vm-${N} --seconds ${WINDOW}"
    FLEET=(
        "${VENV}/bin/python" src/local_stream.py
        --cameras "$N" --interval "$INTERVAL" --seconds "$WINDOW"
        --cloud-url "$URL" --no-display
    )

    if [ "$DRY_RUN" = 1 ]; then
        echo
        echo "== N = ${N} =="
        echo "ssh -i ${VM_KEY} ${VM_USER}@${VM_HOST} \"${RESET}\""
        echo "ssh -i ${VM_KEY} ${VM_USER}@${VM_HOST} \"${MEASURE}\""
        echo "   ${FLEET[*]}"
        echo "   capture -> ${FILE}, ${OUT}/vm-${N}-processing.csv"
        [ "$RESTART" = 1 ] && echo "   restart sls-receiver, wait for health, prime with real frames"
        [ "$COOLDOWN" != 0 ] && echo "   sleep ${COOLDOWN}s"
        continue
    fi

    mkdir -p "$OUT"
    start=$(date +%s)
    echo
    echo ">> N=${N}: restart + prime, reset docroot, stream ${WINDOW}s while sampling the receiver on ${VM_HOST}"
    if [ "$RESTART" = 1 ]; then
        echo "   hard receiver restart (stop -> settle -> start) to reclaim swap"
        ssh -i "$VM_KEY" "$VM_USER@$VM_HOST" 'sudo systemctl stop sls-receiver'
        sleep 5
        ssh -i "$VM_KEY" "$VM_USER@$VM_HOST" 'sudo systemctl start sls-receiver'
        for _ in $(seq 1 30); do
            sleep 2
            curl -s -m 4 "$HEALTH" >/dev/null 2>&1 && break
        done
        sleep 3
        # The receiver's startup warm-up uses a small synthetic frame (480x640),
        # so the first real 1080p frames cost seconds each and build a cold-start
        # queue that contaminates the window. Prime with real frames until the
        # detector is warm; the reset below clears the priming rows.
        echo "   priming the detector with real frames"
        "${VENV}/bin/python" src/local_stream.py --cameras 1 --interval 0.3 \
            --max-samples 12 --cloud-url "$URL" --no-display >/dev/null 2>&1 || true
        sleep 2
    fi
    ssh -i "$VM_KEY" "$VM_USER@$VM_HOST" "$RESET"
    ssh -i "$VM_KEY" "$VM_USER@$VM_HOST" "$MEASURE" > >(tee "$FILE") &
    CAPTURE_PID=$!
    set +e
    "${FLEET[@]}" 2>&1 | tee -a "$FILE"
    FLEET_RC=${PIPESTATUS[0]}
    wait "$CAPTURE_PID"
    CAPTURE_RC=$?
    set -e
    wall=$(( $(date +%s) - start ))

    scp -q -i "$VM_KEY" "$VM_USER@$VM_HOST:${WEB_ROOT}/processing.csv" \
        "$OUT/vm-${N}-processing.csv" 2>/dev/null || echo "   (no processing.csv captured)"
    scp -q -i "$VM_KEY" "$VM_USER@$VM_HOST:${WEB_ROOT}/database.csv" \
        "$OUT/vm-${N}-database.csv" 2>/dev/null || true

    if [ "$FLEET_RC" = 0 ] && [ "$CAPTURE_RC" = 0 ]; then
        echo "vm-${N} : N=${N} x ${WINDOW}s in ${wall}s wall - ok (capture -> ${FILE})"
    else
        echo "vm-${N} : N=${N} x ${WINDOW}s - fleet rc=${FLEET_RC}, measure rc=${CAPTURE_RC} (see ${FILE})"
        FAILED=1
    fi

    if [ "$COOLDOWN" != 0 ]; then
        echo ">> cooldown ${COOLDOWN}s (let swap drain)"
        sleep "$COOLDOWN"
    fi
done

[ "$FAILED" = 0 ]
