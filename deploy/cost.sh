#!/usr/bin/env bash
#
# Read-only cost report for the Part 2 VM and Part 3 serverless resource groups
# (monetary cost: Tasks 2.5 / 3.6 / 4.2 / 4.3).
#
# `az consumption usage list` returns null costs on this student subscription, so this
# queries the Cost Management REST API (`Microsoft.CostManagement/query`) directly, which
# does return real EUR figures. Every call is read-only; nothing changes on Azure.
#
#   bash deploy/cost.sh                                  # both RGs, this month, by day + service
#   bash deploy/cost.sh --from 2026-10-17 --to 2026-10-18
#   bash deploy/cost.sh --rg <resource-group>            # a single resource group
#
# The AI Vision (Foundry Tools) meter posts with a multi-day lag, so a window's Vision cost
# may only appear a few days later — re-run the same window to pick it up.
#
# Required (from .env or the environment): RGS (space-separated resource groups).
# Overridable: FROM, TO, VENV, SUBS.
set -euo pipefail

# shellcheck source=deploy/_env.sh
. "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${VENV:-$REPO_ROOT/venv}"
SUBS="${SUBS:-}"
FROM=""
TO=""

usage() { awk 'NR > 1 && !/^#/ { exit } NR > 1' "$0"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --rg) RGS="$2"; shift 2 ;;
        --from) FROM="$2"; shift 2 ;;
        --to) TO="$2"; shift 2 ;;
        --help | -h) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

# Required from .env / the environment (see .env.example).
require_var RGS

# Default window: the current month through tomorrow (Cost Management treats the `to`
# bound as exclusive, so tomorrow's date includes today).
if [ -z "$FROM" ] || [ -z "$TO" ]; then
    dates=$("${VENV}/bin/python" -c \
        'import datetime as d; t = d.date.today(); print(t.replace(day=1), t + d.timedelta(days=1))')
    FROM="${FROM:-${dates% *}}"
    TO="${TO:-${dates#* }}"
fi

[ -n "$SUBS" ] || SUBS="$(az account show --query id -o tsv)"

# query <rg> <body> -- POST a Cost Management query; rows as TSV.
query() {
    az rest --method post \
        --url "https://management.azure.com/subscriptions/${SUBS}/resourceGroups/$1/providers/Microsoft.CostManagement/query?api-version=2023-11-01" \
        --body "$2" --query "properties.rows" -o tsv
}

day_body=$(printf '{"type":"ActualCost","timeframe":"Custom","timePeriod":{"from":"%sT00:00:00Z","to":"%sT00:00:00Z"},"dataset":{"granularity":"Daily","aggregation":{"totalCost":{"name":"Cost","function":"Sum"}}}}' "$FROM" "$TO")
svc_body=$(printf '{"type":"ActualCost","timeframe":"Custom","timePeriod":{"from":"%sT00:00:00Z","to":"%sT00:00:00Z"},"dataset":{"granularity":"None","aggregation":{"totalCost":{"name":"Cost","function":"Sum"}},"grouping":[{"type":"Dimension","name":"ServiceName"}]}}' "$FROM" "$TO")

printf '>> cost (ActualCost, EUR)  window %s .. %s  (`to` exclusive)\n' "$FROM" "$TO"
for rg in $RGS; do
    echo
    echo "== RG ${rg} =="
    echo "-- by day --"
    query "$rg" "$day_body" | awk -F'\t' '{printf "   %s   %8.4f EUR\n", $2, $1}'
    echo "-- by service --"
    query "$rg" "$svc_body" | sort -t$'\t' -k1,1gr \
        | awk -F'\t' '{s += $1; printf "   %-20s %8.4f EUR\n", $2, $1} END {printf "   %-20s %8.4f EUR\n", "TOTAL", s}'
done
