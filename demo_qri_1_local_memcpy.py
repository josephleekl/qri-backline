#!/usr/bin/env python3
"""Demo 1 through QRI: local CPU to local CPU over memcpy, placement from a reservation.

Same program as backline/demos/demo_1_local_cpu_to_local_cpu_memcpy.py. The difference is where
the nodes come from: the client states a resource intent, the QPM reserves matching inventory
and returns a placement, and nodes_from_placement() builds the Backline from it. No host, path,
or device name appears in this file.

    ./demo_qri_1_local_memcpy.py          in-process mock QPM
    ./demo_qri_1_local_memcpy.py --qfw    QFw's svc_backline_qpm; under `salloc --qpu=backline-local`
                                          the reservation comes from QFW_RESERVATIONS
"""
import getpass
import sys
import time
import uuid
from pathlib import Path

import pennylane as qp

from mock_qpm import MockBacklineQPM
from nodes import nodes_from_placement
from qfw_qpm import QFwBacklineQPM, acquire_placement

INTENT = {
    "version": 1,
    "controller": {"role": "qpu_control", "kind": "cpu"},
    "coprocessors": [{"role": "qec_decoder", "kind": "cpu", "decoder": "steane"}],
    "transport": {"preferred": "memcpy"},
    "qec": {"code": "steane"},
}


def make_request(intent):
    # owner / job_id / scope_id / target_device_id / walltime_ns are what the qfw-slurm gateway
    # sends; QFw's admission (qhw-admission) needs them. The mock ignores them.
    job = f"qri-demo-{uuid.uuid4().hex[:8]}"
    return {
        "owner": {"user": getpass.getuser()},
        "job_id": job,
        "scope_id": job,
        "target_device_id": "backline-local",
        "walltime_ns": 60_000_000_000,
        "workload_kind": "quantum",
        "task_class": {"count": 1, "qubit_count": 3, "depth": 3, "shots": 10},
        "ttl_ns": 60_000_000_000,
        "resource_intent": intent,
    }


def main():
    if "--qfw" in sys.argv[1:]:
        qpm = QFwBacklineQPM.connect()
    else:
        qpm = MockBacklineQPM.from_inventory(Path(__file__).with_name("inventory.toml"))

    caps = qpm.query()
    print("offered:", {k: caps.get(k) for k in ("qec_codes", "controller_kinds",
                                                  "coprocessor_kinds", "transports")})

    try:
        placement, rid, owned = acquire_placement(qpm, make_request(INTENT))
    except RuntimeError as e:
        sys.exit(str(e))
    print(f"reservation {rid}{'' if owned else ' (from Slurm)'}: placement {placement}")

    try:
        dev = nodes_from_placement(placement)

        @qp.qjit(capture=True)
        @qp.set_shots(10)
        @qp.qnode(dev, mcm_method="one-shot")
        def ghz():
            qp.Hadamard(0)
            qp.CNOT([0, 1])
            qp.CNOT([1, 2])
            return qp.sample([qp.measure(0), qp.measure(1), qp.measure(2)])

        t0 = time.perf_counter_ns()
        samples = ghz()
        t1 = time.perf_counter_ns()
        print("samples:", samples)
        print(f"wall time (compile + run): {(t1 - t0) / 1e6:.1f} ms")
    finally:
        if owned:  # a Slurm reservation is released by the allocation's teardown
            print("release:", qpm.release(reservation_id=rid))

    # The intent is checked, not merely accepted.
    bad = qpm.reserve(request=make_request({**INTENT, "qec": {"code": "surface_code"}}))
    print(f"surface_code request {bad['status']}: {bad['reason']}: {bad['message']}")


if __name__ == "__main__":
    main()
