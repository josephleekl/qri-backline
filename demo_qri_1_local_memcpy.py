#!/usr/bin/env python3
"""Backline demo 1 through QRI, with the classical QEC resources requested explicitly.

Two requests: the quantum reservation (made by Slurm from #SBATCH --qpu=..., or here directly when
not under Slurm), and this program's request for the classical QEC resources it needs
(intents/*.yaml). QFw's Backline QPM grants a placement: a controller and a decoder on a
QPM-managed executor, connected over memcpy. Run through qfw-srun in an activated QFw environment.

    demo_qri_1_local_memcpy.py [--intent intents/cpu-steane-memcpy.yaml]
"""
import argparse
import getpass
import os
import time
import uuid
from pathlib import Path

import pennylane as qp
import yaml

from nodes import nodes_from_placement
from qfw_qpm import QFwBacklineQPM, acquire_placement

HERE = Path(__file__).resolve().parent
SHOTS = 10


def quantum_request():
    # Fields the qfw-slurm gateway sends and qhw-admission needs; under Slurm the reservation
    # already exists and these identify the caller (owner, job) for the classical request.
    job = os.environ.get("SLURM_JOB_ID") or f"qri-demo-{uuid.uuid4().hex[:8]}"
    return {
        "owner": {"user": getpass.getuser()},
        "job_id": job,
        "scope_id": job,
        "target_device_id": "backline-local",
        "walltime_ns": 60_000_000_000,
        "workload_kind": "quantum",
        "task_class": {"count": 1, "qubit_count": 3, "depth": 3, "shots": SHOTS},
        "ttl_ns": 60_000_000_000,
    }


def program(dev):
    """The QEC program: Steane-encoded GHZ (Backline demo 1). Change this function to change the demo."""
    @qp.qjit(capture=True)
    @qp.set_shots(SHOTS)
    @qp.qnode(dev, mcm_method="one-shot")
    def ghz():
        qp.Hadamard(0)
        qp.CNOT([0, 1])
        qp.CNOT([1, 2])
        return qp.sample([qp.measure(0), qp.measure(1), qp.measure(2)])
    return ghz


def describe_intent(intent):
    c = intent.get("controller", {})
    d = intent.get("coprocessors", [{}])
    return (f"controller {c.get('kind', 'any')} · "
            + " · ".join(f"decoder {x.get('kind', 'any')} ({x.get('decoder', 'any')})" for x in d)
            + f" · transport {intent.get('transport', {}).get('preferred', 'any')}")


def describe_placement(placement):
    where = placement["controller"]["executor"]["address"]
    return (f"controller {placement['controller']['name']} · "
            + " · ".join(f"decoder {p['name']}" for p in placement["coprocessors"])
            + f" · executor {where}")


def main():
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--intent", default=str(HERE / "intents" / "cpu-steane-memcpy.yaml"))
    args = args.parse_args()

    qpm = QFwBacklineQPM.connect()
    intent = yaml.safe_load(Path(args.intent).read_text())
    quantum = quantum_request()
    budget = quantum["task_class"]

    try:
        placement, rid, owned = acquire_placement(qpm, quantum, intent)
    except RuntimeError as e:
        raise SystemExit(str(e))
    if not owned:  # Slurm made the quantum reservation: show what it granted, not our request
        budget = qpm.get_reservation(reservation_id=rid)["request_metadata"]["task_class"]
    origin = "requested via Slurm" if not owned else "requested by this program"
    print(f"[quantum]   reservation {rid} on backline-local: {budget['count']} circuit, "
          f"≤{budget['qubit_count']} logical qubits, ≤{budget['shots']} shots   ({origin})")
    print(f"[classical] requested: {describe_intent(intent)}   (requested by this program)")
    print(f"[classical] granted:   {describe_placement(placement)}")

    try:
        run = program(nodes_from_placement(placement))
        print(f"[run]       Steane-encoded GHZ, {SHOTS} shots, decoded in real time on the reserved decoder")
        t0 = time.perf_counter_ns()
        samples = run()
        print("samples:", samples)
        print(f"wall time (compile + run): {(time.perf_counter_ns() - t0) / 1e6:.1f} ms")
    finally:
        if owned:  # a Slurm reservation is released by the allocation's teardown
            qpm.release(reservation_id=rid)


if __name__ == "__main__":
    main()
