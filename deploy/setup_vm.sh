#!/usr/bin/env bash
#
# Provision the Azure VM to run the SLS cloud receiver (Part 2).
#
# Run it ON the VM from the checkout root:
#   bash deploy/setup_vm.sh
#   bash deploy/setup_vm.sh --unit-only      # just (re)render + install the unit
#
# Idempotent: safe to re-run. Assumes passwordless sudo (as on the course VM).
# It adds swap (the VM has ~887 MiB RAM and no swap, which torch needs), installs
# the system/OpenCV runtime packages, builds the venv, installs CPU PyTorch and
# the project, runs a detection smoke test, then renders deploy/sls-receiver.service
# (a template with @...@ placeholders) with this machine's values and installs it.
#
# Override via the environment or the repo-root .env (see .env.example):
#   SWAP_SIZE=1G VENV=~/venv TORCH_INDEX=... bash deploy/setup_vm.sh
#
# The unit's values default to this machine, so nothing has to be configured:
#   UNIT_USER     run-as user (default: $SUDO_USER, else the invoking user)
#   UNIT_WORKDIR  ExecStart working directory (default: this checkout root)
#   UNIT_VENV     venv prefix for the unit's Python (default: $VENV)
#   WEB_ROOT      Apache document root the receiver writes into (/var/www/html)
set -euo pipefail

# shellcheck source=deploy/_env.sh
. "$(dirname "${BASH_SOURCE[0]}")/_env.sh"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV="${VENV:-$REPO_ROOT/venv}"
SWAP_SIZE="${SWAP_SIZE:-2G}"
SWAPFILE="${SWAPFILE:-/swapfile}"
TORCH_INDEX="${TORCH_INDEX:-https://download.pytorch.org/whl/cpu}"

UNIT_USER="${UNIT_USER:-${SUDO_USER:-$(id -un)}}"
UNIT_WORKDIR="${UNIT_WORKDIR:-$REPO_ROOT}"
UNIT_VENV="${UNIT_VENV:-$VENV}"
WEB_ROOT="${WEB_ROOT:-/var/www/html}"
UNIT_TEMPLATE="$REPO_ROOT/deploy/sls-receiver.service"
UNIT_DEST="${UNIT_DEST:-/etc/systemd/system/sls-receiver.service}"
APT_PACKAGES=(
    python3-venv
    python3-pip
    python3-dev
    build-essential
    libgl1
    libglib2.0-0
)

log() { printf '\n=== %s ===\n' "$*"; }

# Escape sed's replacement metacharacters in a substituted value.
sed_escape() { printf '%s' "$1" | sed -e 's/[\\&|]/\\&/g'; }

# install_unit -- render deploy/sls-receiver.service with this machine's values
# and install it. The unit is a template (@SLS_USER@, @SLS_WORKDIR@, @SLS_VENV@,
# @WEB_ROOT@) because systemd cannot expand environment variables in `User=`;
# see the template's header comment.
install_unit() {
    local rendered
    rendered="$(sed \
        -e "s|@SLS_USER@|$(sed_escape "$UNIT_USER")|g" \
        -e "s|@SLS_WORKDIR@|$(sed_escape "$UNIT_WORKDIR")|g" \
        -e "s|@SLS_VENV@|$(sed_escape "$UNIT_VENV")|g" \
        -e "s|@WEB_ROOT@|$(sed_escape "$WEB_ROOT")|g" \
        "$UNIT_TEMPLATE")"
    if printf '%s\n' "$rendered" | grep -q '@[A-Z_][A-Z_]*@'; then
        echo "error: a placeholder was left unsubstituted in $UNIT_TEMPLATE" >&2
        exit 1
    fi
    printf '   User=%s  WorkingDirectory=%s  ExecStart=%s/bin/python\n' \
        "$UNIT_USER" "$UNIT_WORKDIR" "$UNIT_VENV"
    printf '%s\n' "$rendered" | sudo tee "$UNIT_DEST" >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable --now sls-receiver.service
    printf '   sls-receiver: %s\n' "$(systemctl is-active sls-receiver.service)"
}

if [ "${1:-}" = "--unit-only" ]; then
    log "systemd unit (--unit-only)"
    install_unit
    echo "unit rendered to $UNIT_DEST"
    exit 0
fi

log "swap ($SWAP_SIZE at $SWAPFILE)"
if swapon --show | grep -q "$(basename "$SWAPFILE")"; then
    echo "swap already active"
else
    sudo fallocate -l "$SWAP_SIZE" "$SWAPFILE"
    sudo chmod 600 "$SWAPFILE"
    sudo mkswap "$SWAPFILE" >/dev/null
    sudo swapon "$SWAPFILE"
    grep -qF "$SWAPFILE" /etc/fstab || echo "$SWAPFILE none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null
    echo "swap created"
fi
free -m | sed -n '2,3p'

log "system packages"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${APT_PACKAGES[@]}"

log "virtualenv ($VENV)"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip

log "PyTorch (CPU wheels, $TORCH_INDEX)"
"$VENV/bin/pip" install --quiet --no-cache-dir torch torchvision --index-url "$TORCH_INDEX"

log "project dependencies"
"$VENV/bin/pip" install --quiet --no-cache-dir -e .

log "smoke test"
if PYTHONPATH=src "$VENV/bin/python" - <<'PY'
import cv2
import numpy as np
import torch

from detection import PersonDetector

print("opencv", cv2.__version__)
print("torch", torch.__version__, "(cuda:", torch.cuda.is_available(), ")")
count, _ = PersonDetector().count_persons(np.zeros((480, 640, 3), np.uint8))
print("detector ok, count =", count)
PY
then
    echo "setup complete"
else
    echo "WARNING: smoke test failed (weights may be downloaded on the first frame)" >&2
fi

log "systemd unit ($UNIT_DEST)"
install_unit
