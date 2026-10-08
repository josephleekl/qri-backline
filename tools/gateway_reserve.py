#!/usr/bin/env python3
"""Stand-in for the qfw-slurm gateway: reserve backline-local's quantum budget only (no intent)
and print the QFW_RESERVATIONS tuple. With --release RID, release it instead."""
import getpass
import json
import os
import sys
import uuid

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from qfw_qpm import QFwBacklineQPM  # noqa: E402

qpm = QFwBacklineQPM.connect()
if sys.argv[1:2] == ["--release"]:
    print(qpm.release(reservation_id=sys.argv[2]))
    sys.exit(0)
job = os.environ.get("SLURM_JOB_ID") or f"gw-{uuid.uuid4().hex[:8]}"
d = qpm.reserve(request={
    "owner": {"user": getpass.getuser()}, "job_id": job, "scope_id": job,
    "target_device_id": "backline-local", "walltime_ns": 120_000_000_000,
    "task_class": {"count": 1, "qubit_count": 3, "depth": 3, "shots": 10}})
if d.get("status") != "accepted":
    sys.exit(f"gateway reserve rejected: {d}")
print(json.dumps([[qpm.service_id, str(d["reservation_id"])]]))
