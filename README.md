# qri-backline

Backline demo 1 with its controller/coprocessor/transport obtained through a mock of QFw's QPM
reservation API instead of `placement.py`.

Run (Python 3.12, `pennylane-catalyst==0.16.0b1` and PennyLane/Lightning `0.46.0b1` installed):

    python check_mock_qpm.py           # mock QPM self-check, no PennyLane needed
    python demo_qri_1_local_memcpy.py  # reserve -> placement -> qjit -> release, then a rejected surface_code request
    python check_qfw_qpm.py            # QFw client adapter self-check (mock stands in for QFw)

Against a live QFw (`svc_backline_qpm`, QFw branch `backline-qpm`), single host:

    QFW_PREFIX=<qfw install> QFW_VENV=<qfw venv> BACKLINE_VENV=<py3.12 venv with Catalyst> \
        tools/run_live_qfw.sh

It starts the directory service and `backline-local` (`qfw-setup --profile local
--service-id backline-local`), runs the demo with `--qfw` through `qfw-srun` twice (direct
reserve, then Slurm-style with a gateway stand-in and `QFW_RESERVATIONS`), and tears down.
The Backline venv also needs DEFw's client deps: `pip install PyYAML jsonschema netifaces
psutil paramiko rich`.
