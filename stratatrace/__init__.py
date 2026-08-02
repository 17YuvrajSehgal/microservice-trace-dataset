"""
StrataTrace loader SDK — one-call access to the four-modality incident dataset.

    from stratatrace import load_run, list_runs
    run = load_run(".../anomaly_mem_aggressive_steady_r1")
    df = run.kernel_l1()          # per-service, 1s-window kernel KPIs

See `loader.py` for the Run API and `derive_kernel_l1.py` for the L1 kernel deriver.
Representation ladder (msr-research.md §4): L0 raw CTF · L1 KPIs (done) · L2 per-request wait
attribution (roadmap) · L3 NL digest (roadmap).
"""
from .loader import Run, load_run, list_runs

__all__ = ["Run", "load_run", "list_runs"]
__version__ = "0.1.0"
