#!/usr/bin/env python3
"""Self-check for qfw_qpm.py without a QFw service plane: a small fake stands in for the QPM."""
import os

from qfw_qpm import QFwBacklineQPM, acquire_placement, reservation_from_env

INTENT = {"version": 1, "controller": {"role": "qpu_control", "kind": "cpu"},
          "coprocessors": [{"role": "qec_decoder", "kind": "cpu", "decoder": "steane"}],
          "transport": {"preferred": "memcpy"}, "qec": {"code": "steane"}}
QUANTUM = {"owner": {"user": "u"}, "job_id": "j", "task_class": {"qubit_count": 3}}
SURFACE = {**INTENT, "qec": {"code": "surface_code"}}


class FakeQPM:
    """QFw's Backline QPM in miniature: accepts steane, rejects any other code."""
    def __init__(self):
        self.requests = []

    def reserve(self, token=None, request=None):
        self.requests.append(request)
        if request["resource_intent"]["qec"]["code"] != "steane":
            return {"status": "rejected", "reason": "unsupported-qec-code", "message": "x"}
        return {"status": "accepted", "reservation_id": request.get("for_reservation", "1"),
                "placement": {"version": 1}}


def expect_error(call, *words):
    try:
        call()
    except RuntimeError as e:
        assert all(w in str(e) for w in words), e
        return
    raise AssertionError(f"expected RuntimeError mentioning {words}")


def main():
    # QFW_RESERVATIONS parsing: absent, ours, someone else's only
    # (the gateway writes the service name; the directory may use qpm:<provider>:<name>)
    os.environ.pop("QFW_RESERVATIONS", None)
    assert reservation_from_env() is None
    os.environ["QFW_RESERVATIONS"] = '[["backline-local","7"],["fake-iqm","8"]]'
    assert reservation_from_env() == ("backline-local", "7")
    os.environ["QFW_RESERVATIONS"] = '[["fake-iqm","8"],["qpm:backline:backline-local","9"]]'
    assert reservation_from_env() == ("qpm:backline:backline-local", "9")
    os.environ["QFW_RESERVATIONS"] = '[["backline-site-a","5"]]'
    assert reservation_from_env() == ("backline-site-a", "5")      # single entry, as QFw selects
    os.environ["QFW_RESERVATIONS"] = '[["fake-iqm","8"],["nwqsim","3"]]'
    assert reservation_from_env() is None
    os.environ.pop("QFW_RESERVATIONS")

    # direct: one reserve carries quantum + classical; the client owns the release
    fake = FakeQPM()
    qpm = QFwBacklineQPM(fake, properties={"qec_codes": ["steane"]})
    assert qpm.query() == {"qec_codes": ["steane"]}
    placement, rid, owned = acquire_placement(qpm, QUANTUM, INTENT)
    assert owned and rid == "1" and placement == {"version": 1}
    assert fake.requests[-1] == {**QUANTUM, "resource_intent": INTENT}
    expect_error(lambda: acquire_placement(qpm, QUANTUM, SURFACE), "unsupported-qec-code")

    # Slurm: the gateway reserved R; the program's classical request names R
    qpm = QFwBacklineQPM(fake, properties={}, reservation_id="7")
    placement, rid, owned = acquire_placement(qpm, QUANTUM, INTENT)
    assert not owned and rid == "7" and placement == {"version": 1}
    assert fake.requests[-1] == {**QUANTUM, "for_reservation": "7", "resource_intent": INTENT}
    expect_error(lambda: acquire_placement(qpm, QUANTUM, SURFACE),
                 "classical QEC request rejected", "unsupported-qec-code")

    print("qfw_qpm: all checks passed")


if __name__ == "__main__":
    main()
