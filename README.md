# qri-backline

Backline demo 1 with its controller/coprocessor/transport obtained through a mock of QFw's QPM
reservation API instead of `placement.py`.

Run (Python 3.12, `pennylane-catalyst==0.16.0b1` and PennyLane/Lightning `0.46.0b1` installed):

    python check_mock_qpm.py           # mock QPM self-check, no PennyLane needed
    python demo_qri_1_local_memcpy.py  # reserve -> placement -> qjit -> release, then a rejected surface_code request
