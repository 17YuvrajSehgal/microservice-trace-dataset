"""Fixtures for the logkit tests. The synthetic data itself is in logkit_synth.py, a module
with a unique name, so the logkit and spankit tests can run in one pytest call."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))      # Blueprint/, for `import logkit`

from logkit_synth import write_run  # noqa: E402


@pytest.fixture(scope="session")
def runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("runs")
    return {"fault": write_run(root, "synthetic_fault_r1", True),
            "normal": write_run(root, "synthetic_normal_r1", False)}


@pytest.fixture(scope="session")
def indexes(runs, tmp_path_factory):
    from logkit.index import build_index, write_index
    from logkit.profile import load_profile

    out = tmp_path_factory.mktemp("idx")
    prof = load_profile("docker_compose")
    paths = {}
    for k, run in runs.items():
        p = out / f"{run.name}.logidx.json.gz"
        write_index(build_index(run, prof), p)
        paths[k] = p
    return paths
