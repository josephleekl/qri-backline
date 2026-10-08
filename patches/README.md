# Patches for QFw and QFw-SLURM-Cluster

The server side of this demo lives in two openQSE repositories. Rather than forks, it is
kept here as `git format-patch` series, each applying on top of a pinned upstream commit.

| Directory | Upstream repository | Base commit | Adds |
| --- | --- | --- | --- |
| `QFw/` | [openQSE/QFw](https://github.com/openQSE/QFw) | `8cc5098` (main, 2026-10-07) | `svc_backline_qpm`, the Backline QPM |
| `QFw-SLURM-Cluster/` | [openQSE/QFw-SLURM-Cluster](https://github.com/openQSE/QFw-SLURM-Cluster) | `708702d` (main, 2026-10-07) | A `qec-backline-head` node and `--qpu=backline-local` |

## Apply

```bash
git clone https://github.com/openQSE/QFw && cd QFw
git checkout -b backline-qpm 8cc5098
git am /path/to/qri-backline/patches/QFw/*.patch

git clone https://github.com/openQSE/QFw-SLURM-Cluster && cd QFw-SLURM-Cluster
git checkout -b backline-qpm 708702d
git am /path/to/qri-backline/patches/QFw-SLURM-Cluster/*.patch
```

## QFw: the Backline QPM

A QPM that hands out Backline controllers, decoders and transports but never runs circuits;
the application compiles and runs the program on the placement it receives. QFw core
(controller, admission, QRI APIs, circuit payload) is unchanged.

| File | Change |
| --- | --- |
| `services/svc_backline_qpm/matcher.py` | New: matches a `resource_intent` against the site inventory |
| `services/svc_backline_qpm/svc_qpm.py` | New: `UTIL_QPM` subclass. Gateway reservations are quantum-only; a `reserve` with `for_reservation` + `resource_intent` requests the classical QEC resources, starts the reservation's executor and attaches the placement (a direct `reserve` with an intent does both at once); `get_reservation` returns the placement while the reservation is active; `release`, expiry and shutdown stop the executor and free the components |
| `services/svc_backline_qpm/executors.py` | New: starts and stops one `catalyst-executor` per reservation |
| `services/svc_backline_qpm/svc_qrc.py` | New: refuses `sync_run` / `async_run` |
| `services/svc_backline_qpm/__init__.py`, `inventory.yaml` | New: registration as `backline-local`; default inventory (CPU controller and Steane decoder over memcpy) |
| `tests/mock/test_backline_qpm.py`, `tests/mock/test_backline_executors.py` | New: tests in QFw's mock harness |
| `share/qfw/config/services/site-services.yaml`, `local-services.yaml` | One `backline-local` entry each |
| `backends/qfw_qiskit/qpm_selection.py` | One `backline` provider entry |

Start it like any QFw QPM, e.g. on one host: `qfw-setup --profile local --service-id backline-local`.
The decoder libraries are found through `CATALYST_LIB` (default: the installed `catalyst`
package's `lib/`); `QFW_BACKLINE_INVENTORY` overrides the inventory file.

## QFw-SLURM-Cluster: deployment

Makes `backline-local` a Slurm resource in the containerised QFw cluster. Configuration only.

| File | Change |
| --- | --- |
| `docker-compose.yml`, `slurm.conf`, `tools/provision-qfw-cluster.sh` | A `qec-backline-head` node, same image as the other nodes |
| `config/site-services.yaml` | The `backline-local` service, loading the `backline` environment module |
| `config/device-access.yaml`, `config/qpu-users.json` | Device record; `backline-local` enabled for the cluster's existing users |
| `config/qfw-slurm/resources.lua`, `config/qfw-slurm/plugin.conf` | `--qpu=backline-local` |
| `modulefiles/backline`, `tools/install-backline-venv.sh` | New: a shared Catalyst venv, `CATALYST_LIB` and the demo checkout |
| `tools/qfw-site-services` | Opt-in `--target backline` start, stop, status |
| `docs/backline.md` | New: setup and an example batch script |

A job requests its quantum resources with `#SBATCH --qpu=backline-local ...` and its classical
QEC resources from the program; see [`examples/job.sh`](../examples/job.sh).
