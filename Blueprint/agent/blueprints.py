#!/usr/bin/env python3
"""Blueprint support: load a blueprint markdown as the agent's injected skill, and give the
agent a tool that runs the blueprint's own scripts.

A blueprint is a self-contained folder (the `Blueprint/latency/1_svc_cpu_cap/` template):

    <folder>/README_v1.md    the blueprint text (what the fault is, the step-by-step method)
    <folder>/tools/          the scripts the method tells the investigator to run

`load(md_path)` wraps the markdown into a skillreg.Skill (so agent_v2's existing skill
injection carries the full method into the worker/synthesiser prompts) and finds the sibling
tools/ dir. `make_tool_def(tools_dir)` builds the `blueprint_tool` schema with the actual
scripts enumerated. `run(...)` executes one script with placeholder expansion:

    $TRACE  the run's CTF kernel trace dir (the folder holding `metadata`)
    $WORK   a per-run scratch dir for slices and notes
    $DUMP   the decoded trace text (trace.txt), when the run bundle carries trace.txt.gz

Environments without babeltrace2/bash (e.g. this Windows dev box) still work:
extract_slice.sh falls back to a pure-Python cut of the decoded dump - same output contract
(scheduling events only, within the window), so sched_budget/rhythm/victim_info/wake_graph
run unchanged.
"""
from __future__ import annotations
import gzip
import json
import os
import re
import shutil
import subprocess
import sys

import skillreg

RUNNABLE = (".py", ".sh")
TIMEOUT_S = 300
RAW_STDOUT_CAP = 400_000     # transcript keeps this much; the per-tool SENT cap trims further


# --------------------------------------------------------------------------------------
# Loading a blueprint as a Skill
# --------------------------------------------------------------------------------------
def load(md_path: str):
    """Read a blueprint markdown -> (skillreg.Skill, tools_dir_or_None).

    The Skill's body is the full blueprint text (that is what gets injected into the
    prompts); its signature is the "what it looks like" section when one exists, so the
    evidence-driven selector can use blueprints too once there are several.
    """
    md_path = os.path.abspath(md_path)
    text = open(md_path, encoding="utf-8").read()
    folder = os.path.dirname(md_path)

    m = re.search(r"^#\s+(.+)$", text, re.M)
    title = (m.group(1).strip() if m else os.path.basename(folder))
    # "Blueprint: finding a CPU cap..." -> keep it; the short name comes from the folder:
    # "1_svc_cpu_cap" -> "svc_cpu_cap".
    name = re.sub(r"^\d+_", "", os.path.basename(folder))

    sig = ""
    sm = re.search(r"^###?\s+[\d.]*\s*What it looks like.*?$\n(.*?)(?=^###?\s)", text,
                   re.M | re.S)
    if sm:
        sig = sm.group(1).strip()
    if not sig:
        sig = text[:1500]

    sk = skillreg.Skill(name=name, covers=name, path=md_path, authored_by="human",
                        signature=sig, boundaries="", body=text)
    tools_dir = os.path.join(folder, "tools")
    return sk, (tools_dir if os.path.isdir(tools_dir) else None)


# --------------------------------------------------------------------------------------
# The blueprint_tool
# --------------------------------------------------------------------------------------
def list_scripts(tools_dir: str) -> list:
    return sorted(f for f in os.listdir(tools_dir)
                  if f.endswith(RUNNABLE) and not f.startswith("_"))


def make_tool_def(tools_dir: str) -> dict:
    scripts = list_scripts(tools_dir)
    return {
        "name": "blueprint_tool",
        "description": (
            "Run one of the blueprint's own scripts - the exact tools its method tells you "
            "to use, with the exact command-line arguments the blueprint shows. Three "
            "placeholders are expanded in args: $TRACE = this run's kernel trace folder "
            "(holds `metadata`), $WORK = a scratch folder for slices and notes (persists "
            "across calls), $DUMP = the full decoded trace text file, when the run has one. "
            "Example, from the blueprint's Step 3: script='extract_slice.sh', "
            "args=['$TRACE','2026-10-11','18:02:10','10','$WORK/s_180210.txt'], then "
            "script='sched_budget.py', args=['$WORK/s_180210.txt','10']. "
            "Returns the script's stdout/stderr and exit code."),
        "parameters": {"type": "object", "properties": {
            "script": {"type": "string", "enum": scripts,
                       "description": "which blueprint script to run"},
            "args": {"type": "array", "items": {"type": "string"},
                     "description": "command-line arguments, exactly as the blueprint shows "
                                    "them ($TRACE/$WORK/$DUMP are expanded)"},
            "why": {"type": "string",
                    "description": "one line: which blueprint step this is"}},
            "required": ["script", "args"]},
    }


def find_trace_dir(run_dir: str):
    """The CTF trace folder = the one holding `metadata`. LTTng nests it (trace/kernel/...)."""
    for root, dirs, files in os.walk(run_dir):
        if "metadata" in files and ("index" in dirs or any(f.startswith("channel") for f in files)):
            return root
    return None


class Runner:
    """Executes blueprint scripts for one run. One instance per diagnose()/Chat."""

    def __init__(self, tools_dir: str, run_dir: str, workdir: str):
        self.tools_dir = tools_dir
        self.run_dir = run_dir
        self.workdir = workdir
        os.makedirs(workdir, exist_ok=True)
        self.trace_dir = find_trace_dir(run_dir)
        self._dump = None            # decoded trace text, materialized on first use

    def dump_path(self):
        if self._dump is None:
            gz = os.path.join(self.run_dir, "trace.txt.gz")
            txt = os.path.join(self.run_dir, "trace.txt")
            if os.path.exists(txt):
                self._dump = txt
            elif os.path.exists(gz):
                out = os.path.join(self.workdir, "trace.txt")
                if not os.path.exists(out):
                    with gzip.open(gz, "rt", errors="replace") as f, \
                         open(out, "w", encoding="utf-8", newline="\n") as o:
                        shutil.copyfileobj(f, o)
                self._dump = out
            else:
                self._dump = ""
        return self._dump

    def _expand(self, a: str) -> str:
        a = a.replace("$TRACE", self.trace_dir or "$TRACE")
        if "$WORK" in a:
            a = a.replace("$WORK", self.workdir)
            # The blueprint names slices after times ($WORK/s_03:17:26.txt). Colons are
            # illegal in NTFS filenames, so sanitize the part under the workdir. Applied
            # identically on write and read, so later calls find the same file.
            head, tail = a[:len(self.workdir)], a[len(self.workdir):]
            a = head + tail.replace(":", "-")
        if "$DUMP" in a:
            a = a.replace("$DUMP", self.dump_path() or "$DUMP")
        return a

    def run(self, script: str, args: list) -> dict:
        # A tool failure must reach the model as data, never kill the investigation.
        try:
            return self._run(script, args)
        except Exception as e:                                          # noqa: BLE001
            return {"cmd": [script, *(args or [])], "error": repr(e)[:400]}

    def _run(self, script: str, args: list) -> dict:
        if script not in list_scripts(self.tools_dir):
            return {"error": f"unknown script {script!r}",
                    "available": list_scripts(self.tools_dir)}
        argv = [self._expand(str(a)) for a in (args or [])]
        if "$TRACE" in " ".join(argv):
            return {"error": "this run has no CTF trace folder (no `metadata` found), "
                             "so $TRACE cannot be expanded. Work from $DUMP instead."}
        path = os.path.join(self.tools_dir, script)

        if script == "extract_slice.sh" and not (shutil.which("bash")
                                                 and shutil.which("babeltrace2")):
            return self._extract_slice_fallback(argv)

        cmd = (["bash", path] if script.endswith(".sh") else [sys.executable, path]) + argv
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                               cwd=self.workdir, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return {"cmd": [script, *argv], "error": f"timed out after {TIMEOUT_S}s"}
        except FileNotFoundError as e:
            return {"cmd": [script, *argv], "error": f"interpreter missing: {e}"}
        out = p.stdout[:RAW_STDOUT_CAP]
        return {"cmd": [script, *argv], "exit": p.returncode, "stdout": out,
                "stdout_truncated": len(p.stdout) > RAW_STDOUT_CAP,
                "stderr": p.stderr[-4000:]}

    def _extract_slice_fallback(self, argv: list) -> dict:
        """extract_slice.sh without bash/babeltrace2: cut the window out of the decoded
        dump and keep only scheduling events - the same output contract, so the
        downstream scripts (sched_budget/rhythm/victim_info/wake_graph) run unchanged."""
        if len(argv) != 5:
            return {"error": "usage: extract_slice.sh <trace_dir> <YYYY-MM-DD> <HH:MM:SS> "
                             "<seconds> <out_file>"}
        _trace, day, start, secs, out = argv
        dump = self.dump_path()
        if not dump:
            return {"error": "no babeltrace2 on this machine and the run has no decoded "
                             "trace.txt.gz - cannot cut a slice here."}
        try:
            h, m_, s = (int(x) for x in start.split(":"))
            t0 = h * 3600 + m_ * 60 + s
            t1 = t0 + float(secs)
        except ValueError:
            return {"error": f"bad start time {start!r}, want HH:MM:SS"}
        ts_re = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\.(\d{9})\]")
        kept = 0
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(dump, encoding="utf-8", errors="replace") as f, \
             open(out, "w", encoding="utf-8", newline="\n") as o:
            for line in f:
                if "sched_switch" not in line and "sched_waking" not in line \
                        and "sched_wakeup" not in line:
                    continue
                mm = ts_re.match(line)
                if not mm:
                    continue
                t = int(mm.group(1)) * 3600 + int(mm.group(2)) * 60 + int(mm.group(3)) \
                    + int(mm.group(4)) / 1e9
                if t0 <= t < t1:
                    o.write(line)
                    kept += 1
        return {"cmd": ["extract_slice.sh", *argv], "exit": 0,
                "stdout": f"slice {day} {start} + {secs}s -> {out}\n{kept} {out}",
                "stderr": "(python fallback: no babeltrace2 here; cut from the decoded "
                          "dump. Same content contract: scheduling events in the window.)"}
