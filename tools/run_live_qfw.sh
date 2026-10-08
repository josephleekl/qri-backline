#!/usr/bin/env bash
# Run the demo against a live, single-host QFw service plane (directory + svc_backline_qpm).
#
#   QFW_PREFIX=...  QFW_VENV=...  BACKLINE_VENV=...  tools/run_live_qfw.sh
#
# QFW_VENV runs the services; BACKLINE_VENV (Python 3.12, Catalyst) runs the client through
# qfw-srun, which puts that venv's site-packages first. Both paths are exercised:
#   1. direct: the demo reserves with its intent and releases
#   2. Slurm-style: a gateway stand-in makes the quantum reservation; the demo requests its
#      classical resources against it (QFW_RESERVATIONS); the gateway releases
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
: "${QFW_PREFIX:?}" "${QFW_VENV:?}" "${BACKLINE_VENV:?}"
export QFW_SHARED_ROOT=${QFW_SHARED_ROOT:-$(mktemp -d)}
export CATALYST_LIB=${CATALYST_LIB:-$("$BACKLINE_VENV/bin/python" -c 'import importlib.util,pathlib;print(pathlib.Path(list(importlib.util.find_spec("catalyst").submodule_search_locations)[0])/"lib")')}
cd "$here"

source "$QFW_PREFIX/bin/qfw-activate" --venv "$QFW_VENV"
qfw-setup --profile local --service-id backline-local
trap 'qfw-teardown || true' EXIT

source "$QFW_PREFIX/bin/qfw-activate" --venv "$BACKLINE_VENV"
echo "== 1. direct"
qfw-srun demo_qri_1_local_memcpy.py --intent intents/cpu-steane-memcpy.yaml
echo "== 2. Slurm-style"
export SLURM_JOB_ID="live-$$"
tuple=$(qfw-srun tools/gateway_reserve.py | tail -1)
QFW_RESERVATIONS="$tuple" qfw-srun demo_qri_1_local_memcpy.py --intent intents/cpu-steane-memcpy.yaml
QFW_RESERVATIONS="$tuple" qfw-srun tools/gateway_reserve.py --release "$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])[0][1])' "$tuple")"
