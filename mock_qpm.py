"""In-process stand-in for a QFw QPM that serves Backline placements.

Method names and keyword signatures follow QFw's service-apis/api_qpm_admission_control
(evaluate, reserve, release, get_reservation) and the QPM query() pattern, so phase 2 can move
this into services/svc_backline_qpm as a UTIL_QPM subclass. placement() stands in for the
proposed QRI get_placement(reservation_id).
"""
import copy
import importlib.util
import itertools
import os
import string
import time
import tomllib
from pathlib import Path

PLACEMENT_VERSION = 1
DEFAULT_TTL_NS = 60_000_000_000


class _Reject(Exception):
    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


def _rejected(reason, message):
    return {"status": "rejected", "reason": reason, "message": message}


def _field(obj, key):
    """obj[key] as a dict; missing means {}, anything else is an invalid request."""
    value = obj.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _Reject("invalid-request", f"{key} must be an object, got {type(value).__name__}")
    return value


def _default_catalyst_lib():
    spec = importlib.util.find_spec("catalyst")
    if spec is None or not spec.submodule_search_locations:
        return ""
    return str(Path(list(spec.submodule_search_locations)[0]) / "lib")


class MockBacklineQPM:
    def __init__(self, inventory, clock=time.time_ns):
        self.inventory = inventory
        self._clock = clock
        self._ids = itertools.count(1)
        self._reservations = {}

    @classmethod
    def from_inventory(cls, path, clock=time.time_ns):
        env = dict(os.environ)
        if not env.get("CATALYST_LIB"):
            env["CATALYST_LIB"] = _default_catalyst_lib()
        try:
            text = string.Template(Path(path).read_text()).substitute(env)
        except KeyError as e:
            raise ValueError(f"inventory {path} uses unset variable {e}") from None
        inventory = tomllib.loads(text)
        for decoder in inventory.get("decoder", []):
            if not Path(decoder["lib"]).is_file():
                raise FileNotFoundError(
                    f"decoder {decoder['id']!r}: library not found: {decoder['lib']}")
        return cls(inventory, clock)

    # ---------------------------------------------------------------- discovery

    def query(self, token=None):
        inv = self.inventory
        return {
            "provider": "backline",
            "placement_version": PLACEMENT_VERSION,
            "qec_codes": sorted({d["code"] for d in inv.get("decoder", [])}),
            "controller_kinds": sorted({c["hardware"] for c in inv.get("controller", [])}),
            "coprocessor_kinds": sorted({c["hardware"] for c in inv.get("coprocessor", [])}),
            "transports": sorted({t for c in inv.get("controller", []) for t in c["transports"]}),
            "decoders": [
                {"id": d["id"], "code": d["code"], "hardware": d["hardware"],
                 "round_trip_us_p50": d.get("round_trip_us_p50")}
                for d in inv.get("decoder", [])
            ],
        }

    # ---------------------------------------------------------------- admission

    def evaluate(self, token=None, request=None):
        # Non-binding, like QFW_GW_EVALUATE: checks admissibility, holds nothing.
        try:
            self._match(request, self._busy())
        except _Reject as r:
            return _rejected(r.reason, str(r))
        return {"status": "accepted"}

    def reserve(self, token=None, request=None):
        if isinstance(request, dict) and request.get("reservation_id") not in (None, 0, "0"):
            return _rejected("caller-selected-reservation-id", "the QPM issues reservation IDs")
        try:
            ctrl, chosen, wires, transport, code = self._match(request, self._busy())
        except _Reject as r:
            return _rejected(r.reason, str(r))
        rid = str(next(self._ids))
        now = self._clock()
        expires = now + request.get("ttl_ns", DEFAULT_TTL_NS)
        placement = {
            "version": PLACEMENT_VERSION,
            "controller": {"name": ctrl["id"], "hardware": ctrl["hardware"],
                           "device": {"name": ctrl["devices"][0], "wires": wires}},
            "coprocessors": [
                {"name": c["id"], "hardware": c["hardware"],
                 "function": {"symbol": d["symbol"], "lib_path": d["lib"]}}
                for c, d in chosen
            ],
            "transport": transport,
            "qec_code": code,
        }
        self._reservations[rid] = {
            "reservation_id": rid, "state": "active",
            "created_at_ns": now, "expires_at_ns": expires,
            "entries": [ctrl["id"]] + [c["id"] for c, _ in chosen],
            "placement": placement,
        }
        return {"status": "accepted", "reservation_id": rid, "expires_at_ns": expires,
                "placement": copy.deepcopy(placement)}

    def release(self, token=None, reservation_id=None, reason=None):
        r = self._reservations.get(str(reservation_id))
        if r is None:
            return _rejected("unknown-reservation", f"no reservation {reservation_id}")
        self._sweep()
        if r["state"] == "active":
            r["state"] = "released"
        # Idempotent: releasing a released or expired reservation succeeds.
        return {"status": "accepted", "reservation_id": r["reservation_id"], "state": r["state"]}

    def get_reservation(self, token=None, reservation_id=None):
        r = self._reservations.get(str(reservation_id))
        if r is None:
            return _rejected("unknown-reservation", f"no reservation {reservation_id}")
        self._sweep()
        out = {k: r[k] for k in ("reservation_id", "state", "created_at_ns", "expires_at_ns")}
        if r["state"] == "active":
            out["placement"] = copy.deepcopy(r["placement"])
        return out

    def placement(self, token=None, reservation_id=None):
        r = self._reservations.get(str(reservation_id))
        if r is None:
            raise ValueError(f"unknown reservation: reservation_id={reservation_id}")
        self._sweep()
        if r["state"] == "expired":
            raise ValueError(f"expired reservation: reservation_id={r['reservation_id']}")
        if r["state"] != "active":
            raise ValueError(f"invalid reservation for placement: state={r['state']}")
        return copy.deepcopy(r["placement"])

    # ---------------------------------------------------------------- internals

    def _sweep(self):
        now = self._clock()
        for r in self._reservations.values():
            if r["state"] == "active" and now >= r["expires_at_ns"]:
                r["state"] = "expired"

    def _busy(self):
        self._sweep()
        return {e for r in self._reservations.values() if r["state"] == "active"
                for e in r["entries"]}

    def _match(self, request, busy):
        """Matching steps 1-4 against the whole inventory, then step 5 (capacity)."""
        if not isinstance(request, dict):
            raise _Reject("invalid-request", "request must be a dict")
        intent = request.get("resource_intent")
        if not isinstance(intent, dict) or intent.get("version") != PLACEMENT_VERSION:
            raise _Reject("invalid-request", "resource_intent with version 1 is required")
        wires = _field(request, "task_class").get("qubit_count")
        if type(wires) is not int or wires < 1:
            raise _Reject("invalid-request", "task_class.qubit_count (logical qubits) must be an int >= 1")
        ttl = request.get("ttl_ns", DEFAULT_TTL_NS)
        if type(ttl) is not int or ttl < 1:
            raise _Reject("invalid-request", "ttl_ns must be an int >= 1")
        wanted = intent.get("coprocessors") or [{"role": "qec_decoder"}]
        if not isinstance(wanted, list) or not all(isinstance(w, dict) for w in wanted):
            raise _Reject("invalid-request", "resource_intent.coprocessors must be a list of objects")
        code = _field(intent, "qec").get("code")
        transport = _field(intent, "transport").get("preferred")
        kind = _field(intent, "controller").get("kind")
        limit = _field(intent, "latency").get("max_round_trip_us")
        inv = self.inventory

        # 1. QEC code
        codes = sorted({d["code"] for d in inv.get("decoder", [])})
        if code not in codes:
            raise _Reject("unsupported-qec-code",
                          f"qec code {code!r} is not offered; supported: {codes}")

        # 2. controller (kind hint, capacity in wires)
        ctrls = [c for c in inv.get("controller", [])
                 if kind in (None, c["hardware"]) and c["max_wires"] >= wires]
        if not ctrls:
            raise _Reject("no-matching-controller",
                          f"no controller of kind {kind!r} with {wires} wires")

        if transport is not None:
            return self._match_on(transport, ctrls, wanted, code, limit, wires, busy)
        # Outcome-only intent: first transport that the controller and
        # every coprocessor share; report the first transport's reason if none fits.
        first = None
        for t in sorted({t for c in ctrls for t in c["transports"]}):
            try:
                return self._match_on(t, ctrls, wanted, code, limit, wires, busy)
            except _Reject as r:
                first = first or r
        raise first or _Reject("unsupported-transport", "no controller lists a transport")

    def _match_on(self, transport, ctrls, wanted, code, limit, wires, busy):
        inv = self.inventory
        ctrls = [c for c in ctrls if transport in c["transports"]]
        if not ctrls:
            raise _Reject("unsupported-transport",
                          f"no matching controller supports transport {transport!r}")

        # 3-4. each coprocessor: decoder, transport, latency
        options = []
        for i, want in enumerate(wanted):
            if want.get("decoder") == "client":
                raise _Reject("client-decoder-unsupported",
                              "client-defined decoders are not supported in phase 1")
            ck = want.get("kind")
            decoders = [d for d in inv.get("decoder", [])
                        if d["code"] == code and ck in (None, d["hardware"])
                        and want.get("decoder") in (None, d["code"], d["id"])]
            opts = [(c, d) for c in inv.get("coprocessor", []) for d in decoders
                    if c["hardware"] == d["hardware"]]
            if not opts:
                raise _Reject("no-matching-coprocessor",
                              f"coprocessor {i}: no {ck or 'any'} decoder for {code!r}")
            opts = [(c, d) for c, d in opts if transport in c["transports"]]
            if not opts:
                raise _Reject("unsupported-transport",
                              f"coprocessor {i}: no option supports transport {transport!r}")
            if limit is not None:
                measured = [(c, d) for c, d in opts if d.get("round_trip_us_p50") is not None]
                if not measured:
                    raise _Reject("latency-unverified",
                                  f"coprocessor {i}: no measured round trip to check against {limit} us")
                opts = [(c, d) for c, d in measured if d["round_trip_us_p50"] <= limit]
                if not opts:
                    raise _Reject("latency-unattainable",
                                  f"coprocessor {i}: no decoder meets {limit} us")
            options.append(opts)

        # 5. capacity: exclusive, first free choice per role
        # ponytail: greedy assignment; can miss a fit with several interchangeable
        # coprocessors of different reach. Bipartite matching if inventories grow.
        taken = set(busy)
        ctrl = next((c for c in ctrls if c["id"] not in taken), None)
        if ctrl is None:
            raise _Reject("capacity-exhausted", "every matching controller is reserved")
        taken.add(ctrl["id"])
        chosen = []
        for i, opts in enumerate(options):
            pick = next(((c, d) for c, d in opts if c["id"] not in taken), None)
            if pick is None:
                raise _Reject("capacity-exhausted",
                              f"coprocessor {i}: every matching coprocessor is reserved")
            taken.add(pick[0]["id"])
            chosen.append(pick)
        return ctrl, chosen, wires, transport, code
