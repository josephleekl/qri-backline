"""Turn a QPM placement into PennyLane Backline nodes.

The only client-side code that knows the placement schema. Replaces demos/placement.py: nothing
here is site-specific; every value comes from the reservation's placement.
"""
import pennylane as qp

_REMOTE_FIELDS = ("executor", "endpoint")


def nodes_from_placement(placement):
    if placement.get("version") != 1:
        raise ValueError(f"unsupported placement version {placement.get('version')!r}")
    nodes = [placement["controller"], *placement["coprocessors"]]
    remote = [n["name"] for n in nodes if any(f in n for f in _REMOTE_FIELDS)]
    if remote:
        # ponytail: local placements only; remote nodes map executor/endpoint onto
        # executor_options/endpoint in a later phase.
        raise NotImplementedError(f"remote placement for {remote} is not supported in phase 1")

    c = placement["controller"]
    ctrl = qp.Controller(
        name=c["name"], device=qp.device(c["device"]["name"], wires=c["device"]["wires"]))
    coprocs = [
        qp.Coprocessor(
            name=p["name"],
            coprocessor_fn=qp.CoprocessorFunction(
                p["function"]["symbol"], lib_path=p["function"]["lib_path"]))
        for p in placement["coprocessors"]
    ]
    return qp.Backline(controller=ctrl, coprocessors=coprocs,
                       transport=placement["transport"], qec_code=placement["qec_code"])
