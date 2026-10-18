#!/usr/bin/env bash
#
# Read-only metrics collector for the Part 3 serverless pipeline (Task 3.6).
#
# Collects the server-side telemetry of the deployed pipeline for a time window
# and prints a consolidated report: response time (Application Insights / Log
# Analytics), and compute / AI / storage cost proxies (Azure Monitor metrics).
# It changes nothing on Azure — every call is a query (`show`, `list`, `query`).
#
# This is the server-side complement of the client-side probe
# `src/measure_serverless.py` (upload->visible latency); together they mirror
# Part 2's `src/load_test.py` + `deploy/measure.sh`.
#
#   bash deploy/measure_part3.sh --minutes 15
#   bash deploy/measure_part3.sh --minutes 60
#
# Cost (EUR) is not queried here: this student subscription returns null costs
# via `az consumption`; read actual spend from Portal > Cost Management, scoped
# to the resource group. Everything else below is collected by az.
#
# Required (from .env or the environment): RG, FUNC, STORAGE, VISION.
# Overridable: SUBS (event subscription name).
set -euo pipefail

# shellcheck source=deploy/_env.sh
. "$(dirname "${BASH_SOURCE[0]}")/_env.sh"
SUBS="${SUBS:-raw-blob-created}"
MINUTES=15

while [ $# -gt 0 ]; do
    case "$1" in
        --minutes) MINUTES="$2"; shift 2 ;;
        --rg) RG="$2"; shift 2 ;;
        --func) FUNC="$2"; shift 2 ;;
        --storage) STORAGE="$2"; shift 2 ;;
        --vision) VISION="$2"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

# Required from .env / the environment (see .env.example).
require_var RG FUNC STORAGE VISION

OFFSET="${MINUTES}m"

# --- resolve resource ids (read-only) --------------------------------------
FUNC_ID=$(az functionapp show -n "$FUNC" -g "$RG" --query id -o tsv)
STORAGE_ID=$(az storage account show -n "$STORAGE" -g "$RG" --query id -o tsv)
VISION_ID=$(az cognitiveservices account show -n "$VISION" -g "$RG" --query id -o tsv)
SUB_ID="${STORAGE_ID}/providers/Microsoft.EventGrid/eventSubscriptions/${SUBS}"
# Event Grid metrics for a system-topic setup live on the topic, not the subscription.
STOPIC_ID=$(az eventgrid system-topic show -n "${STORAGE}-raw" -g "$RG" \
    --query id -o tsv 2>/dev/null || true)
AI_ID=$(az monitor app-insights component show -a "$FUNC" -g "$RG" \
    --query workspaceResourceId -o tsv 2>/dev/null || true)
WS_CID=""
if [ -n "${AI_ID:-}" ] && [ "$AI_ID" != "None" ]; then
    WS_CID=$(az monitor log-analytics workspace show --ids "$AI_ID" \
        --query customerId -o tsv 2>/dev/null || true)
fi

# Sum a metric's Total over the window (blank/unsupported -> 0).
metric_total() {
    local out
    out=$(az monitor metrics list --resource "$1" --metric "$2" --interval PT1M \
        --aggregation Total --offset "$OFFSET" \
        --query "value[].timeseries[].data[].total" -o tsv 2>/dev/null || true)
    printf "%s" "$out" | tr '\t' '\n' | awk 'NF{u+=$1} END{printf "%.0f", u+0}'
}

mb() { awk -v v="$1" 'BEGIN{printf "%.2f MB", v/1048576}'; }

echo "== Part 3 server-side metrics =="
echo "window      : last ${MINUTES} min"
echo "rg          : ${RG}"
echo "function    : ${FUNC}   storage: ${STORAGE}   vision: ${VISION}"

# --- response time (Application Insights / Log Analytics) ------------------
echo
echo "-- response time (server-side, process_frame) --"
if [ -n "${WS_CID:-}" ]; then
    az monitor log-analytics query -w "$WS_CID" --analytics-query "
        AppRequests
        | where Name == 'process_frame' and TimeGenerated > ago(${MINUTES}m)
        | summarize calls=count(), succeeded=countif(Success), failed=countif(Success == false),
                    min_ms=round(min(DurationMs)), avg_ms=round(avg(DurationMs)),
                    p95_ms=round(percentile(DurationMs, 95)), max_ms=round(max(DurationMs))
        | project calls, succeeded, failed, min_ms, avg_ms, p95_ms, max_ms
    " -o table 2>/dev/null || echo "  (no Log Analytics data)"
    echo "-- exceptions --"
    az monitor log-analytics query -w "$WS_CID" --analytics-query "
        AppExceptions | where TimeGenerated > ago(${MINUTES}m) | summarize exceptions=count()
    " -o table 2>/dev/null || echo "  (no Log Analytics data)"
else
    echo "  (could not resolve Log Analytics workspace; check FUNC/AI name)"
fi

# --- compute (Functions Flex) ----------------------------------------------
echo
echo "-- compute (Functions Flex) --"
execs=$(metric_total "$FUNC_ID" OnDemandFunctionExecutionCount)
units=$(metric_total "$FUNC_ID" OnDemandFunctionExecutionUnits)
printf "executions        : %s\n" "$execs"
printf "execution units   : %s  (MB.ms; the billable compute unit)\n" "$units"

# --- AI Vision --------------------------------------------------------------
echo
echo "-- AI Vision --"
printf "calls             : %s (successful %s)\n" \
    "$(metric_total "$VISION_ID" TotalCalls)" "$(metric_total "$VISION_ID" SuccessfulCalls)"
printf "latency (sum, ms) : %s\n" "$(metric_total "$VISION_ID" Latency)"

# --- storage ----------------------------------------------------------------
echo
echo "-- storage (${STORAGE}) --"
printf "transactions      : %s\n" "$(metric_total "$STORAGE_ID" Transactions)"
printf "ingress           : %s\n" "$(mb "$(metric_total "$STORAGE_ID" Ingress)")"
printf "egress            : %s  (browser polling of the static site dominates)\n" \
    "$(mb "$(metric_total "$STORAGE_ID" Egress)")"

# --- event delivery ---------------------------------------------------------
echo
echo "-- event grid (system topic ${STORAGE}-raw) --"
EVENT_RESOURCE="${STOPIC_ID:-$SUB_ID}"
printf "published / matched / delivered / failed : %s / %s / %s / %s\n" \
    "$(metric_total "$EVENT_RESOURCE" PublishSuccessCount)" \
    "$(metric_total "$EVENT_RESOURCE" MatchedEventCount)" \
    "$(metric_total "$EVENT_RESOURCE" DeliverySuccessCount)" \
    "$(metric_total "$EVENT_RESOURCE" DeliveryAttemptFailCount)"

# --- cost -------------------------------------------------------------------
echo
echo "-- monetary cost --"
echo "  read from Portal > Cost Management > Cost analysis (scope RG ${RG})."
echo "  (az consumption returns null costs on this student subscription.)"

echo
echo "note: combine with the client probe for upload->visible latency:"
echo "  venv/bin/python src/measure_serverless.py --frames 10 --interval 0.5"
