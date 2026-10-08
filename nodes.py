"""Turn a QPM placement into PennyLane Backline nodes.

The only client-side code that knows the placement schema; every value comes from the
reservation's placement. The controller and decoders run on the executor the QPM started for the
reservation (one process, so memcpy connects them).
"""
import pennylane as qp
from catalyst.executor import Executor


def nodes_from_placement(placement):
    if placement.get("version") != 1:
        raise ValueError(f"unsupported placement version {placement.get('version')!r}")
    nodes = [placement["controller"], *placement["coprocessors"]]
    if any("endpoint" in n for n in nodes):
        raise NotImplementedError("RDMA endpoints in a placement are not supported yet")
    addresses = {n.get("executor", {}).get("address") for n in nodes}
    if len(addresses) != 1 or None in addresses:
        raise ValueError(f"placement must put every node on one executor, got {addresses}")
    shared = {"remote": True, "executor": Executor(addresses.pop()).launch()}

    c = placement["controller"]
    ctrl = qp.Controller(name=c["name"], hardware=c["hardware"],
                         device=qp.device(c["device"]["name"], wires=c["device"]["wires"]),
                         **shared)
    coprocs = [
        qp.Coprocessor(name=p["name"], hardware=p["hardware"],
                       coprocessor_fn=qp.CoprocessorFunction(
                           p["function"]["symbol"], lib_path=p["function"]["lib_path"]),
                       **shared)
        for p in placement["coprocessors"]
    ]
    return qp.Backline(controller=ctrl, coprocessors=coprocs,
                       transport=placement["transport"], qec_code=placement["qec_code"])
