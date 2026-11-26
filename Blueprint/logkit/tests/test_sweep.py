"""The scorer-side sweep (Blueprint/eval/log_sweep.py) on the synthetic runs."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "eval"))

import log_sweep as S  # noqa: E402


def test_fault_run_is_scored_against_its_label(runs, indexes):
    row = S.score_run(runs["fault"], indexes["fault"])
    assert row["family"] == "synthetic_fault" and not row["normal"]
    assert row["onset"]["entity"] == "front-end" and row["onset"]["is_target"]
    assert abs(row["onset"]["dt"]) < 1
    assert row["role"] == "culprit_logs" and "catalogue" in row["window"]


def test_normal_run_has_no_false_alarm(runs, indexes):
    row = S.score_run(runs["normal"], indexes["normal"])
    assert row["normal"] and row["role"] == "n/a"
    assert "onset" not in row and row["window"] == {}
    table = S.summarise([row, S.score_run(runs["fault"], indexes["fault"])])
    assert "False alarms: log_onset 0, log_window 0" in table
    assert "| synthetic_fault | 1 | 1 | 0 | 1 |" in table
