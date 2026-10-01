"""Reach the Backline QPM through QFw instead of the in-process mock.

QFwBacklineQPM wraps QFw's admission binding for the `backline-local` service
(`svc_backline_qpm` in QFw) with the same methods as MockBacklineQPM, so the demo runs against
either. Under Slurm (`salloc --qpu=backline-local`) the gateway has already reserved, and
QFW_RESERVATIONS names the reservation: the client then reads the placement and leaves the
release to Slurm's teardown.
"""
import json
import os

SERVICE_ID = "backline-local"


def reservation_from_env(service_id=SERVICE_ID):
    """(service_id, reservation_id) for this QPM from QFW_RESERVATIONS, or None.

    The entry naming service_id (bare, or as qpm:<provider>:<name>); else the only entry, as
    QFw's select_qpm_reservation does when a single QPM is reserved.
    """
    entries = [(str(sid), str(rid))
               for sid, rid in json.loads(os.environ.get("QFW_RESERVATIONS") or "[]")]
    named = [e for e in entries if e[0] == service_id or e[0].endswith(":" + service_id)]
    if named:
        return named[0]
    return entries[0] if len(entries) == 1 else None


def _qpm_resolver():
    # qfw_qiskit/__init__.py imports Qiskit; the resolver does not. Load the package without
    # its __init__ when Qiskit is absent, as QFw's own mock test conftest does.
    try:
        from qfw_qiskit.qpm_resolver import QPMResolver
    except ModuleNotFoundError as e:
        if e.name is None or not e.name.startswith("qiskit"):
            raise
        import importlib.util
        import sys
        import types
        spec = importlib.util.find_spec("qfw_qiskit")
        package = types.ModuleType("qfw_qiskit")
        package.__path__ = list(spec.submodule_search_locations)
        sys.modules["qfw_qiskit"] = package
        from qfw_qiskit.qpm_resolver import QPMResolver
    return QPMResolver


class QFwBacklineQPM:
    def __init__(self, admission, properties, reservation_id=None, service_id=SERVICE_ID):
        self._admission = admission
        self.service_id = service_id
        self.properties = dict(properties)
        self.reservation_id = reservation_id

    @classmethod
    def connect(cls, timeout=10):
        # Needs an activated QFw environment (qfw-activate) and a running directory service.
        import defw
        from defw_app_util import defw_get_directory_service
        QPMResolver = _qpm_resolver()

        resolver = QPMResolver.from_environment(
            dirsvc=defw_get_directory_service(timeout=timeout), defw_module=defw)
        reserved = reservation_from_env()
        if reserved is not None:
            sid, rid = reserved
            bound = resolver.connect_reserved_managed(
                sid, rid, timeout=timeout, api_category="admission")
            return cls(bound.client, bound.resolved.properties or {}, rid, sid)
        resolved = resolver.resolve(timeout=timeout, api_category="admission",
                                    provider="backline")
        client = resolver.managed_binding(resolved).api(
            resolved.api_binding.binding_name, expected_runtime_id=resolved.runtime_id)
        return cls(client, resolved.properties or {}, service_id=resolved.service_id)

    def query(self, token=None):
        return dict(self.properties)

    def reserve(self, token=None, request=None):
        return self._admission.reserve(token=token, request=request)

    def release(self, token=None, reservation_id=None, reason=None):
        return self._admission.release(token=token, reservation_id=reservation_id, reason=reason)

    def get_reservation(self, token=None, reservation_id=None):
        return self._admission.get_reservation(token=token, reservation_id=reservation_id)


def acquire_placement(qpm, request):
    """(placement, reservation_id, owned). owned=False when Slurm reserved and will release."""
    rid = getattr(qpm, "reservation_id", None)
    if rid is not None:
        placement = qpm.get_reservation(reservation_id=rid).get("placement")
        if placement is None:
            raise RuntimeError(f"reservation {rid} carries no placement (released or expired?)")
        return placement, rid, False
    decision = qpm.reserve(request=request)
    if decision.get("status") != "accepted":
        raise RuntimeError(f"rejected: {decision.get('reason')}: {decision.get('message')}")
    return decision["placement"], decision["reservation_id"], True
