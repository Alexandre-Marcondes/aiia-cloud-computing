#!/usr/bin/env bash
#
# Sample VM resource usage around a load window (Practice 1, Part 2.5).
#
# Run it ON the VM from the checkout root. It records the receiver's CPU time,
# cgroup memory, and the NIC byte counters at the start and end of a window,
# prints the deltas, and (with --self-load) drives the load itself.
#
#   bash deploy/measure.sh baseline --seconds 15        # idle / external load
#   bash deploy/measure.sh inference --self-load --frames 20
#
# Overridable: SERVICE (sls-receiver), IFACE (eth0), VENV, URL.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

SERVICE="${SERVICE:-sls-receiver}"
IFACE="${IFACE:-eth0}"
VENV="${VENV:-$REPO_ROOT/venv}"
URL="${URL:-http://127.0.0.1:8000}"
NPROC="$(nproc)"

LABEL="${1:-measurement}"
[ $# -gt 0 ] && shift

SECONDS_WINDOW=15
SELF_LOAD=0
FRAMES=20
while [ $# -gt 0 ]; do
    case "$1" in
        --seconds) SECONDS_WINDOW="$2"; shift 2 ;;
        --self-load) SELF_LOAD=1; shift ;;
        --frames) FRAMES="$2"; shift 2 ;;
        --url) URL="$2"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

read_cpu() { systemctl show "$SERVICE" -p CPUUsageNSec --value 2>/dev/null || echo 0; }
read_mem() { systemctl show "$SERVICE" -p MemoryCurrent --value 2>/dev/null || echo 0; }
read_peak() { systemctl show "$SERVICE" -p MemoryPeak --value 2>/dev/null || echo 0; }
# /proc/net/dev: field 1 is the interface, field 2 received bytes, field 10 sent bytes.
read_net() { awk -v i="$IFACE:" '$1 == i { print $2, $10 }' /proc/net/dev; }

cpu0=$(read_cpu)
net0=$(read_net)
t0=$(date +%s.%N)

if [ "$SELF_LOAD" = 1 ]; then
    PYTHONPATH=src "$VENV/bin/python" src/load_test.py --url "$URL" --frames "$FRAMES"
else
    echo ">> sampling ${SECONDS_WINDOW}s -- generate external load now"
    sleep "$SECONDS_WINDOW"
fi

t1=$(date +%s.%N)
cpu1=$(read_cpu)
net1=$(read_net)
mem=$(read_mem)
peak=$(read_peak)

awk -v label="$LABEL" -v iface="$IFACE" -v n="$NPROC" \
    -v cpu0="$cpu0" -v cpu1="$cpu1" -v t0="$t0" -v t1="$t1" \
    -v net0="$net0" -v net1="$net1" -v mem="$mem" -v peak="$peak" \
    'BEGIN {
        wall = t1 - t0;
        cpu_s = (cpu1 - cpu0) / 1e9;
        split(net0, a, " "); split(net1, b, " ");
        rx = (b[1] - a[1]) / 1048576; tx = (b[2] - a[2]) / 1048576;
        printf "\n== %s ==\n", label;
        printf "window          : %.1f s\n", wall;
        printf "cpu (process)   : %.2f s  (%.0f%% of one core, %.0f%% of all)\n",
               cpu_s, 100 * cpu_s / wall, 100 * cpu_s / (wall * n);
        printf "memory (cgroup) : current %.0f MB, peak %.0f MB\n", mem / 1048576, peak / 1048576;
        printf "network %-7s : rx %.2f MB (%.2f Mbps), tx %.2f MB (%.2f Mbps)\n",
               iface, rx, 8 * rx / wall, tx, 8 * tx / wall;
    }'

free -m | awk '/^Mem:/ {printf "system memory   : used %d MB, available %d MB\n", $3, $7}
                /^Swap:/ {printf "swap used       : %d MB\n", $3}'
