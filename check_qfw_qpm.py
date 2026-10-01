#!/usr/bin/env python3
"""Self-check for qfw_qpm.py without a QFw service plane.

The mock QPM stands in for QFw's admission binding (same method names), so this checks the
adapter and the placement hand-off: directly reserved, and pre-reserved by Slurm.
"""
import os
import tempfile
from pathlib import Path

from check_mock_qpm import INVENTORY, request as _request
from mock_qpm import MockBacklineQPM
from qfw_qpm import QFwBacklineQPM, acquire_placement, reservation_from_env


def request(**intent):
    # check_mock_qpm's 1 us TTL suits its fake clock; this check runs on the real one.
    return {**_request(**intent), "ttl_ns": 60_000_000_000}


def main():
    tmp = Path(tempfile.mkdtemp())
    (tmp / "libsteane_coprocessor_cpu.so").touch()
    (tmp / "inventory.toml").write_text(INVENTORY)
    os.environ["CATALYST_LIB"] = str(tmp)
    admission = MockBacklineQPM.from_inventory(tmp / "inventory.toml")

    # QFW_RESERVATIONS parsing: absent, ours, someone else's only
    os.environ.pop("QFW_RESERVATIONS", None)
    assert reservation_from_env() is None
    os.environ["QFW_RESERVATIONS"] = '[["backline-local","7"],["fake-iqm","8"]]'
    assert reservation_from_env() == "7"
    os.environ["QFW_RESERVATIONS"] = '[["fake-iqm","8"]]'
    assert reservation_from_env() is None

    # direct: the client reserves, so it owns the release
    qpm = QFwBacklineQPM(admission, properties={"qec_codes": ["steane"]})
    assert qpm.query() == {"qec_codes": ["steane"]}
    placement, rid, owned = acquire_placement(qpm, request())
    assert owned and placement["transport"] == "memcpy", placement
    qpm.release(reservation_id=rid)

    # Slurm: the gateway reserved; the client only reads the placement
    gateway = admission.reserve(request=request())
    qpm = QFwBacklineQPM(admission, properties={}, reservation_id=gateway["reservation_id"])
    placement, rid, owned = acquire_placement(qpm, request())
    assert not owned and rid == gateway["reservation_id"]
    assert placement == gateway["placement"], placement

    # Slurm reservation no longer active: a clear error, not a KeyError
    admission.release(reservation_id=gateway["reservation_id"])
    try:
        acquire_placement(qpm, request())
        raise AssertionError("released Slurm reservation must raise")
    except RuntimeError as e:
        assert "carries no placement" in str(e), e

    # rejected reserve surfaces the QPM's reason
    try:
        acquire_placement(QFwBacklineQPM(admission, {}), request(qec={"code": "surface_code"}))
        raise AssertionError("rejected reserve must raise")
    except RuntimeError as e:
        assert "unsupported-qec-code" in str(e), e

    print("qfw_qpm: all checks passed")


if __name__ == "__main__":
    main()
