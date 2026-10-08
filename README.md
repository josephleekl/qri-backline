# qri-backline

Backline demo 1 (Steane-encoded GHZ, controller and decoder over memcpy) run through QFw's
Backline QPM, with two explicit requests:

1. **Quantum resources**: `#SBATCH --qpu=backline-local ...` (qfw-slurm reserves through QRI).
2. **Classical QEC resources**: the program asks the QPM for a controller, decoder and transport
   ([`intents/cpu-steane-memcpy.yaml`](intents/cpu-steane-memcpy.yaml)) against that
   reservation. The QPM starts a `catalyst-executor` for it; the program compiles locally and
   runs controller and decoder there.

Needs Python 3.12, `pennylane-catalyst==0.16.0b1` and PennyLane/Lightning `0.46.0b1`, plus
DEFw's client deps (`pip install PyYAML jsonschema netifaces psutil paramiko rich`).

    python check_qfw_qpm.py            # client self-check, no QFw needed

On the QFw Slurm cluster (QFw-SLURM-Cluster with [`patches/`](patches/README.md)):

    sbatch examples/job.sh

Single host, against a live QFw with the Backline QPM (QFw plus `patches/QFw`):

    QFW_PREFIX=<qfw install> QFW_VENV=<qfw venv> BACKLINE_VENV=<py3.12 venv with Catalyst> \
        tools/run_live_qfw.sh

It starts the directory service and `backline-local` (`qfw-setup --profile local
--service-id backline-local`), runs the demo through `qfw-srun` twice (one direct reserve; then
Slurm-style, with a gateway stand-in making the quantum reservation), and tears down.

## Patches

The QFw service (`svc_backline_qpm`) and the QFw-SLURM-Cluster wiring (`--qpu=backline-local`)
are in [`patches/`](patches/README.md), as `git am` series against pinned upstream commits.
