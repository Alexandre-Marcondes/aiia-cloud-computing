#!/usr/bin/env bash
#
# Shared configuration loader for the deploy/ scripts.
#
# Every deploy script sources this file, which in turn sources the repo-root
# `.env` (gitignored, machine-specific) if it exists and does nothing if it does
# not. `.env.example` documents every variable. A value already exported in the
# environment wins over the file, so a one-off override needs no edit:
#
#     VM_HOST=1.2.3.4 deploy/sync.sh
#
# Usage, at the top of a deploy script (after `set -euo pipefail`):
#
#     # shellcheck source=deploy/_env.sh
#     . "$(dirname "${BASH_SOURCE[0]}")/_env.sh"
#
# Then declare what the script needs, which stops it loudly when a value is
# missing:
#
#     require_var VM_HOST VM_USER VM_KEY
#
# There are deliberately no hardcoded defaults for cloud resource identifiers or
# machine paths: a missing value must stop the script, never silently target
# somebody else's resources.

_ENV_SH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_REPO_ROOT="$(cd "${_ENV_SH_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${ENV_REPO_ROOT}/.env}"

# Source the caller's .env, exporting everything it defines so the az/ssh/scp
# processes the scripts launch inherit the same values.
if [ -f "${ENV_FILE}" ]; then
    # Remember the values the caller already exported: sourcing the file would
    # otherwise clobber them, and `VM_HOST=... deploy/x.sh` must win.
    _env_saved=()
    while IFS= read -r _env_line || [ -n "${_env_line}" ]; do
        _env_line="${_env_line#"${_env_line%%[![:space:]]*}"}" # strip leading space
        case "${_env_line}" in
            '' | '#'*) continue ;;
        esac
        _env_line="${_env_line#export }"
        _env_key="${_env_line%%=*}"
        case "${_env_key}" in
            '' | *[!A-Za-z0-9_]*) continue ;;
        esac
        if [ -n "${!_env_key+x}" ]; then
            _env_saved+=("${_env_key}=${!_env_key}")
        fi
    done <"${ENV_FILE}"

    set -a
    # shellcheck disable=SC1090  # discovered at runtime, not a static string
    . "${ENV_FILE}"
    set +a

    for _env_kv in "${_env_saved[@]}"; do
        export "${_env_kv}"
    done
    unset _env_saved _env_kv _env_line _env_key
fi

# require_var <name>... -- abort with an actionable message for the first
# variable that is unset or empty.
require_var() {
    local name
    for name in "$@"; do
        if [ -z "${!name:-}" ]; then
            printf 'deploy: %s is not set -- add it to %s (copy .env.example) or export it.\n' \
                "${name}" "${ENV_FILE}" >&2
            exit 2
        fi
    done
}
