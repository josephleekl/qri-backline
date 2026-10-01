#!/usr/bin/env python3
"""Self-check for mock_qpm.py. Needs no PennyLane: run `python check_mock_qpm.py`."""
import os
import tempfile
from pathlib import Path

from mock_qpm import MockBacklineQPM

INVENTORY = """
[[controller]]
id = "local-cpu-ctrl"
hardware = "cpu"
devices = ["null.qubit"]
max_wires = 64
transports = ["memcpy"]

[[coprocessor]]
id = "local-cpu-coproc"
hardware = "cpu"
transports = ["memcpy"]

[[decoder]]
id = "steane-cpu"
code = "steane"
hardware = "cpu"
symbol = "steane_coprocessor"
lib = "${CATALYST_LIB}/libsteane_coprocessor_cpu.so"
"""


def request(**intent_overrides):
    intent = {
        "version": 1,
        "controller": {"role": "qpu_control", "kind": "cpu"},
        "coprocessors": [{"role": "qec_decoder", "kind": "cpu", "decoder": "steane"}],
        "transport": {"preferred": "memcpy"},
        "qec": {"code": "steane"},
    }
    intent.update(intent_overrides)
    return {
        "workload_kind": "quantum",
        "task_class": {"count": 1, "qubit_count": 3, "depth": 3, "shots": 10},
        "ttl_ns": 1_000,
        "resource_intent": intent,
    }


def main():
    tmp = Path(tempfile.mkdtemp())
    (tmp / "libsteane_coprocessor_cpu.so").touch()
    inv = tmp / "inventory.toml"
    inv.write_text(INVENTORY)
    os.environ["CATALYST_LIB"] = str(tmp)
    now = [0]
    qpm = MockBacklineQPM.from_inventory(inv, clock=lambda: now[0])

    # discovery
    assert qpm.query()["qec_codes"] == ["steane"]

    # accept: placement holds exactly the chosen entries, demo-1 shaped
    d = qpm.reserve(request=request())
    assert d["status"] == "accepted", d
    assert d["placement"] == {
        "version": 1,
        "controller": {"name": "local-cpu-ctrl", "hardware": "cpu",
                       "device": {"name": "null.qubit", "wires": 3}},
        "coprocessors": [{"name": "local-cpu-coproc", "hardware": "cpu",
                          "function": {"symbol": "steane_coprocessor",
                                       "lib_path": str(tmp / "libsteane_coprocessor_cpu.so")}}],
        "transport": "memcpy",
        "qec_code": "steane",
    }, d["placement"]
    rid = d["reservation_id"]

    # exclusive: second reserve while the first is active
    assert qpm.reserve(request=request())["reason"] == "capacity-exhausted"
    # release frees it; double release is fine
    assert qpm.release(reservation_id=rid)["status"] == "accepted"
    assert qpm.release(reservation_id=rid)["status"] == "accepted"
    assert "placement" not in qpm.get_reservation(reservation_id=rid)
    assert qpm.get_reservation(reservation_id=rid)["state"] == "released"

    # rejections, in matching order
    def reason(req):
        return qpm.reserve(request=req)["reason"]
    assert reason(request(qec={"code": "surface_code"})) == "unsupported-qec-code"
    assert reason(request(controller={"kind": "fpga"})) == "no-matching-controller"
    assert reason(request(transport={"preferred": "rdma"})) == "unsupported-transport"
    assert reason(request(coprocessors=[{"kind": "gpu", "decoder": "steane"}])) == "no-matching-coprocessor"
    assert reason(request(coprocessors=[{"kind": "cpu", "decoder": "client"}])) == "client-decoder-unsupported"
    assert reason(request(latency={"max_round_trip_us": 5})) == "latency-unverified"
    two = request(coprocessors=[{"kind": "cpu"}, {"kind": "cpu"}])
    assert reason(two) == "capacity-exhausted"                      # Review Focus 5
    no_qubits = request()
    del no_qubits["task_class"]["qubit_count"]
    assert reason(no_qubits) == "invalid-request"                   # Review Focus 2
    caller_id = request()
    caller_id["reservation_id"] = "7"
    assert reason(caller_id) == "caller-selected-reservation-id"
    assert qpm.evaluate(request=request(qec={"code": "surface_code"}))["reason"] == "unsupported-qec-code"
    assert qpm.evaluate(request=request())["status"] == "accepted"

    # expiry frees entries; placement() refuses                       # Review Focus 3
    d = qpm.reserve(request=request())
    assert d["status"] == "accepted", d
    now[0] = d["expires_at_ns"]
    assert qpm.get_reservation(reservation_id=d["reservation_id"])["state"] == "expired"
    try:
        qpm.placement(reservation_id=d["reservation_id"])
        raise AssertionError("placement() on an expired reservation must raise")
    except ValueError as e:
        assert str(e) == f"expired reservation: reservation_id={d['reservation_id']}", e
    assert qpm.reserve(request=request())["status"] == "accepted"

    # missing library fails at load time, naming the path             # Review Focus 1
    os.environ["CATALYST_LIB"] = str(tmp / "nowhere")
    try:
        MockBacklineQPM.from_inventory(inv)
        raise AssertionError("missing decoder library must fail at load")
    except FileNotFoundError as e:
        assert str(tmp / "nowhere" / "libsteane_coprocessor_cpu.so") in str(e), e

    print("mock_qpm: all checks passed")


if __name__ == "__main__":
    main()
