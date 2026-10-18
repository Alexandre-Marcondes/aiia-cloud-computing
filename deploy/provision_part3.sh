#!/usr/bin/env bash
#
# Provision and audit the Part 3 serverless infrastructure (T11): the storage
# containers, the `raw` Event Grid system topic, and the BlobCreated subscription
# that invokes the Function App's blobs extension -- the exact no-recursion
# scoping documented in docs/architecture.md.
#
#   bash deploy/provision_part3.sh audit          # read-only inventory + subscription JSON
#   bash deploy/provision_part3.sh create --yes    # (re)create topics, containers, subscription
#   bash deploy/provision_part3.sh --dry-run       # print every command, change nothing
#   bash deploy/provision_part3.sh --help
#
# `audit` makes only read-only calls (`show`/`list`) and prints app-setting names,
# never their secret values. `create` refuses to run without `--yes` and echoes
# each command before running it. `--dry-run` prints the whole plan (audit and
# create commands) and makes no Azure call at all.
#
# Required (from .env or the environment): STORAGE, RG, FUNC, VISION -- each
# also overridable from .env; see .env.example.
# Also overridable: SUBS, TOPIC, RAW_CONTAINER, WEB_CONTAINER.

set -euo pipefail

# shellcheck source=deploy/_env.sh
. "$(dirname "${BASH_SOURCE[0]}")/_env.sh"
SUBS="${SUBS:-raw-blob-created}"
TOPIC="${TOPIC:-${STORAGE}-raw}"
RAW_CONTAINER="${RAW_CONTAINER:-raw}"
WEB_CONTAINER="${WEB_CONTAINER:-\$web}"

DRY_RUN=0
YES=0
SUB=""

usage() { sed -n '2,/^$/p' "$0"; }

while [ $# -gt 0 ]; do
    case "$1" in
        audit | create) SUB="$1"; shift ;;
        --dry-run | -n) DRY_RUN=1; shift ;;
        --yes) YES=1; shift ;;
        --help | -h) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

# Required from .env / the environment (see .env.example).
require_var STORAGE RG FUNC VISION

# Echo a command, then run it unless this is a dry run.
run() {
    printf '   $ %s\n' "$*"
    [ "$DRY_RUN" = 1 ] || "$@"
}

# Echo a command, then run it best-effort (used for the idempotent delete).
run_ok() {
    printf '   $ %s   (best effort)\n' "$*"
    [ "$DRY_RUN" = 1 ] || "$@" >/dev/null 2>&1 || true
}

audit() {
    echo "== audit: ${STORAGE} / ${FUNC} / ${VISION} in ${RG} (read-only) =="
    echo "-- storage account + containers --"
    run az storage account show -n "$STORAGE" -g "$RG" \
        --query "{id:id, kind:kind, sku:sku.name, location:location, allowBlobPublicAccess:allowBlobPublicAccess}" \
        -o json
    run az storage container list --account-name "$STORAGE" --auth-mode key \
        --query "[].name" -o tsv
    echo "-- AI Vision --"
    run az cognitiveservices account show -n "$VISION" -g "$RG" \
        --query "{id:id, endpoint:properties.endpoint, sku:sku.name, location:location}" -o json
    echo "-- Function App --"
    run az functionapp show -n "$FUNC" -g "$RG" \
        --query "{id:id, defaultHostName:defaultHostName, state:state}" -o json
    echo "-- Function App setting names (values are secrets; never printed) --"
    run az functionapp config appsettings list -n "$FUNC" -g "$RG" \
        --query "[].name" -o tsv
    echo "-- Event Grid system topic ${TOPIC} --"
    run az eventgrid system-topic show -n "$TOPIC" -g "$RG" \
        --query "{id:id, source:source, topicType:topicType, provisioningState:provisioningState}" -o json
    echo "-- subscription ${SUBS} on ${TOPIC} (full JSON) --"
    run az eventgrid system-topic event-subscription list \
        --system-topic-name "$TOPIC" -g "$RG" -o json
}

create() {
    if [ "$DRY_RUN" = 0 ] && [ "$YES" != 1 ]; then
        echo "refusing to create: pass --yes to run the state-changing commands" >&2
        exit 1
    fi

    echo "== create: containers + ${TOPIC} + ${SUBS} =="

    local storage_id function_host
    if [ "$DRY_RUN" = 1 ]; then
        storage_id="/subscriptions/<subscription>/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${STORAGE}"
        function_host="${FUNC}.azurewebsites.net"
    else
        storage_id=$(az storage account show -n "$STORAGE" -g "$RG" --query id -o tsv)
        function_host=$(az functionapp show -n "$FUNC" -g "$RG" --query defaultHostName -o tsv)
    fi
    local webhook="https://${function_host}/runtime/webhooks/blobs"
    local subject_prefix="/blobServices/default/containers/${RAW_CONTAINER}/blobs/"

    echo "-- ensure containers --"
    run az storage container create --name "$RAW_CONTAINER" --account-name "$STORAGE" \
        --auth-mode key --public-access off
    run az storage container create --name "$WEB_CONTAINER" --account-name "$STORAGE" \
        --auth-mode key --public-access blob

    echo "-- ensure Event Grid system topic --"
    run az eventgrid system-topic create --name "$TOPIC" --source "$storage_id" \
        --topic-type Microsoft.Storage.StorageAccounts -g "$RG"

    echo "-- (re)create BlobCreated subscription (${RAW_CONTAINER}/*.jpg only, no recursion) --"
    run_ok az eventgrid system-topic event-subscription delete \
        --system-topic-name "$TOPIC" -g "$RG" --name "$SUBS"
    run az eventgrid system-topic event-subscription create \
        --system-topic-name "$TOPIC" -g "$RG" --name "$SUBS" \
        --endpoint "$webhook" --endpoint-type webhook \
        --included-event-types Microsoft.Storage.BlobCreated \
        --subject-begins-with "$subject_prefix" \
        --subject-ends-with .jpg \
        --max-events-per-batch 1 \
        --event-ttl 1440 --max-delivery-attempts 30
}

if [ "$DRY_RUN" = 1 ]; then
    echo ">> dry-run: printing the full plan; no Azure calls, nothing changed"
    audit
    create
    echo ">> dry-run: nothing was changed"
    exit 0
fi

case "${SUB:-audit}" in
    audit) audit ;;
    create) create ;;
esac
