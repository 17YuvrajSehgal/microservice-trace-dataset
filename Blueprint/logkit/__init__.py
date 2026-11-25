"""logkit: application logs as a witness for the kernel blueprints.

The design is in `Blueprint/latency/LOGS-PLAN.md`. Three layers, kept apart on purpose:

    logkit.profile     how one log FORMAT is read (a YAML file per format in profiles/)
    logkit.index       reads a run's logs once and writes a compact index (needs PyYAML)
    logkit/tools/      the blueprint tools; standard library only, so they can be copied into
                       a blueprint's tools/ folder and run with a bare `python3`

    python -m logkit.build <run_dir> --out <run>.logidx.json.gz [--profile docker_compose]

Everything a tool knows about a run comes from that index file. No tool opens a log file, and
nothing here opens anything in a run directory except the files a profile names.
"""
from logkit.tools.logidx import SCHEMA_VERSION

__all__ = ["SCHEMA_VERSION"]
