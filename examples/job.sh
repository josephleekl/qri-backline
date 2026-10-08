#!/bin/bash
# Backline QEC demo on the QFw Slurm cluster: sbatch -A <account> examples/job.sh
#
# 1. Quantum resources — what QRI / qfw-slurm supports today
#SBATCH --qpu=backline-local --workload-kind=quantum
#SBATCH --circ-count=1 --max-qubits=3 --max-depth=3 --max-shots=10
#SBATCH --job-name=backline-qec-demo
#SBATCH --nodes=1
#SBATCH --ntasks=1
set -euo pipefail
export QFW_SHARED_ROOT=/workspace/qfw-container-base
export QFW_RUN_BASE_DIR="${HOME}/qfw-runs"
module load backline
source "${QFW_PREFIX}/bin/qfw-activate" --venv "${BACKLINE_VENV}"
# Attach this job to the site's QFw services (directory, Backline QPM).
QFW_RUN_TMP_PATH="$(qfw-setup | tail -1)"
export QFW_RUN_TMP_PATH
trap 'qfw-teardown > /dev/null || true' EXIT
Q="${QFW_SHARED_ROOT}/qri-backline"

# 2. Classical QEC resources — what this work adds (see the intent file)
qfw-srun "$Q/demo_qri_1_local_memcpy.py" --intent "$Q/intents/cpu-steane-memcpy.yaml"
