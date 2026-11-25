import re
import shutil
import subprocess
import sys
from pathlib import Path

from conftest import FAULT_LAT_AT, FAULT_NEW_AT, T0
from logkit.tools import log_onset, log_window
from logkit.tools import logidx as L

TOOLS = Path(log_onset.__file__).parent


def hms(off):
    return L.hms(T0 + off)


VERDICT = re.compile(r"^(LOG ONSET|NO LOG CHANGE|LOGS TOO SHORT|NO LOGS|LOG DIFF|NO LOG DIFF"
                     r"|LOG WINDOW OUTSIDE LOGS|LOG CLOCK NOT ALIGNED):")


def verdicts(out):
    return [ln for ln in out.splitlines() if VERDICT.match(ln)]


def test_onset_finds_the_first_change(indexes, capsys):
    assert log_onset.main([str(indexes["fault"])]) == 0
    out = capsys.readouterr().out
    v = verdicts(out)
    assert len(v) == 1 and v[0].startswith("LOG ONSET: front-end (container) first change at %s"
                                           % hms(FAULT_NEW_AT)), out
    assert "ECONNREFUSED" in v[0]
    # windowed signals are found to within one window (WIN_S), counted from the baseline's end
    also = re.search(r"also changed: catalogue (\d\d:\d\d:\d\d)", v[0])
    t = L.resolve_time(also.group(1), T0) - T0
    assert FAULT_LAT_AT <= t <= FAULT_LAT_AT + log_onset.WIN_S, v[0]
    assert "caller of the faulty one" in out           # the witness rule is always printed


def test_onset_is_quiet_on_the_healthy_run(indexes, capsys):
    # front-end logs one 406 error per second all run long: a baseline error is not a change
    log_onset.main([str(indexes["normal"])])
    out = capsys.readouterr().out
    assert verdicts(out)[0].startswith("NO LOG CHANGE"), out
    assert "does not mean the system is healthy" in out


def test_window_reports_each_changed_entity(indexes, capsys):
    args = [str(indexes["fault"]), hms(FAULT_LAT_AT + 20), "20", "--baseline", hms(20), "20"]
    log_window.main(args)
    out = capsys.readouterr().out
    v = verdicts(out)
    assert [x.split(":")[0] for x in v] == ["LOG DIFF", "LOG DIFF"], out
    assert v[0].startswith("LOG DIFF: front-end") and "new warning/error template" in v[0]
    assert v[1].startswith("LOG DIFF: catalogue") and "List p50" in v[1]
    assert "E1" in out and "ECONNREFUSED" in out


def test_window_is_quiet_on_the_healthy_run(indexes, capsys):
    log_window.main([str(indexes["normal"]), hms(120), "20", "--baseline", hms(20), "20"])
    assert verdicts(capsys.readouterr().out)[0].startswith("NO LOG DIFF")


def test_window_outside_the_logs(indexes, capsys):
    log_window.main([str(indexes["fault"]), hms(5000), "10", "--baseline", hms(20), "20"])
    assert verdicts(capsys.readouterr().out)[0].startswith("LOG WINDOW OUTSIDE LOGS")


def test_window_refuses_an_unaligned_clock(indexes, tmp_path, capsys):
    import gzip
    import json
    with gzip.open(indexes["fault"], "rt") as fh:
        d = json.load(fh)
    d["clock"] = {"aligned": False, "offset_s": None}
    p = tmp_path / "unaligned.logidx.json"
    p.write_text(json.dumps(d))
    log_window.main([str(p), hms(120), "20", "--baseline", hms(20), "20"])
    assert verdicts(capsys.readouterr().out)[0].startswith("LOG CLOCK NOT ALIGNED")


def test_tools_run_as_copied_scripts_with_the_standard_library_only(indexes, tmp_path):
    """The harness copies tools into a blueprint's tools/ folder and runs them with python3."""
    for f in ("logidx.py", "logsig.py", "log_onset.py", "log_window.py"):
        shutil.copy(TOOLS / f, tmp_path / f)
    env = {"PATH": "", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    r = subprocess.run([sys.executable, "-E", "-s", str(tmp_path / "log_onset.py"),
                        str(indexes["fault"])], capture_output=True, text=True, env=env,
                       cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "LOG ONSET: front-end" in r.stdout
    src = "".join((tmp_path / f).read_text() for f in ("logidx.py", "logsig.py", "log_onset.py",
                                                       "log_window.py"))
    imports = re.findall(r"^\s*(?:import|from)\s+([\w.]+)", src, re.M)
    assert not {"yaml", "logkit"} & {m.split(".")[0] for m in imports}, imports
