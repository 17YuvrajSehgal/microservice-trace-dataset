#!/usr/bin/env python3
"""Sandboxed Python for the agent, over one run's kernel-trace index.

WHY THIS EXISTS. The registered tools answer a fixed set of questions. Three of our measured
failures are questions they cannot express: summed per-container CPU time (svc_cpu_cap), a
retransmission RATE over a window (anomaly_net), per-flow grouping (svc_net). Letting the agent
write the aggregation itself removes that ceiling.

THE RULE THIS FILE EXISTS TO ENFORCE, restated from ctf_tool.py:

    NOTHING REACHABLE BY THE AGENT MAY READ ground_truth.json.

That rule is harder here than anywhere else, because `ground_truth.json` sits INSIDE each run
directory, beside kernel/. Arbitrary code handed a run path is one open() from the answer, and
`verification.json` and `verification.png` next to it give away the injection window too.

So the sandbox never sees a run directory. It is handed the two derived index files, which
contain counts and raw event lines and no ground truth of any kind:

    dataset/index/<run_id>.tsv.gz     bucket_start_s, event, procname, pid_ns, count
    dataset/index/<run_id>.lines.gz   bucket_start_s, event, procname, pid_ns, raw_line

Four independent barriers, so no single mistake is enough:

  1. NO FILESYSTEM. The snippet runs with a builtins whitelist that has no `open`, no
     `__import__`, no `eval`/`exec`/`compile`. Data arrives as a pre-loaded DataFrame. There is
     no API by which it can name a file at all.
  2. STATIC SCAN. The snippet is parsed to an AST and rejected before it runs if it imports,
     touches a dunder attribute (the standard `__class__.__subclasses__` escape), or mentions a
     forbidden name or path fragment.
  3. KERNEL LIMITS. The child sets RLIMIT_FSIZE to 0, so even a bypass cannot write a byte, plus
     an address-space cap. A wall-clock timeout in the parent kills and restarts it.
  4. AUDIT. Every snippet and its output goes into the transcript, and scan_snippets.py
     re-checks all of them offline. A leak that somehow ran would still be visible afterwards.
"""
from __future__ import annotations
import ast, json, os, subprocess, sys, textwrap, time

INDEX_ROOT = os.environ.get(
    "CTF_INDEX_ROOT", "/scratch/yuvraj17/stratatrace/dataset/index")

TIMEOUT_S = float(os.environ.get("CODETOOL_TIMEOUT", "45"))
OUT_CAP = 12000            # chars of stdout returned to the model
MEM_BYTES = 6 * 1024 ** 3  # address-space cap in the child

# Names a snippet may never mention. `open` and the import machinery are already absent from
# builtins; listing them here turns a runtime NameError into a clear message the agent can act
# on, and catches the case where a future change to the namespace reintroduces one.
BANNED_NAMES = {
    "open", "eval", "exec", "compile", "__import__", "input", "breakpoint", "exit", "quit",
    "globals", "locals", "vars", "getattr", "setattr", "delattr", "memoryview",
    "os", "sys", "subprocess", "socket", "shutil", "pathlib", "glob", "importlib",
    "urllib", "requests", "httpx", "pickle", "marshal", "ctypes", "sysconfig", "builtins",
}
# Substrings that betray an attempt to reach the dataset rather than the index.
BANNED_TEXT = ("ground_truth", "groundtruth", "verification", "dataset/runs", "/runs/",
               "fault_state", "MANIFEST", "SHA256SUMS", "..")


class Rejected(Exception):
    pass


def _scan(code):
    """Reject a snippet before it runs. Raises Rejected with a reason the agent can act on."""
    low = code.lower()
    for bad in BANNED_TEXT:
        if bad.lower() in low:
            raise Rejected(
                "rejected: the snippet mentions %r. This sandbox has the kernel-trace INDEX "
                "only - counts and raw event lines. It has no access to run directories, and "
                "nothing that records what the fault was. Work from the data you have." % bad)
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise Rejected("syntax error on line %s: %s" % (e.lineno, e.msg))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise Rejected(
                "rejected: no imports. pandas as pd, numpy as np, math, statistics, "
                "collections, re, json and datetime are already in scope.")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise Rejected("rejected: dunder attribute %r is not allowed." % node.attr)
        if isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            raise Rejected("rejected: %r is not available in this sandbox." % node.id)


# --------------------------------------------------------------------------------------
# The child. Its own process so a runaway snippet can be killed without taking the agent with
# it, and so the kernel limits apply to it alone. MEM is substituted before launch.
# --------------------------------------------------------------------------------------
_CHILD = '''
import json, resource, sys, os, gzip, io, math, statistics, collections, re, datetime
resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))          # cannot write one byte
resource.setrlimit(resource.RLIMIT_AS, (MEM, MEM))
import pandas as pd, numpy as np

TAB = chr(9)
NL = chr(10)
TSV, LINES = sys.argv[1], sys.argv[2]
_COLS = ["bucket_start_s", "event", "procname", "pid_ns", "count", "value_sum"]
_ncol = len(pd.read_csv(TSV, sep=TAB, comment="#", compression="gzip",
                        nrows=1, header=None).columns)
df = pd.read_csv(TSV, sep=TAB, comment="#", compression="gzip", names=_COLS[:_ncol])
if "value_sum" not in df.columns:
    df["value_sum"] = 0

# THE BARRIER THAT ACTUALLY MATTERS.
#
# Blocking `open` in builtins is not enough, because pandas and numpy do their own file I/O:
# pd.read_csv, pd.read_json, np.load and np.fromfile all take a path and would sail straight
# past any check on Python names. Enumerating every such API is a losing game - the next
# pandas release adds another one.
#
# So instead: keep the one file descriptor we still need, then cap RLIMIT_NOFILE just above it.
# That limit is on descriptor NUMBERS, not on a count - a new open must be assigned a number
# below the limit, and every number below it is already taken. After this line the kernel
# refuses to create a descriptor at all, for any caller, by any route. pd.read_csv fails with
# OSError, and so does whatever pandas adds next release. Measured: with the lines file on fd 3
# and the limit at 4, a fresh open raises OSError while the kept descriptor still reads.
#
# Counting entries in /proc/self/fd instead of using fileno() does NOT work - listdir holds a
# descriptor of its own while it runs, so the count comes back one too high and leaves exactly
# enough headroom for one more open. That was the first version of this line, and the
# adversarial test caught it reading /etc/passwd.
# WARM UP FIRST. pandas and numpy import submodules lazily, on first use of a code path -
# .groupby() pulls in numpy.rec, and the import machinery needs a descriptor to read the .py
# file. Drop the limit before that happens and the sandbox blocks the agent's own analysis
# instead of the attacker: the first groupby dies with "Too many open files: numpy/rec".
# The adversarial test caught this too. So exercise the operations here, while opening files
# is still allowed, and let every lazy import resolve. Running the real operations beats
# listing module names, which would go stale the next time pandas reorganises.
_w = df.head(2000).copy()
_w["k"] = _w["count"] * 1.0
for _op in (
        lambda: _w.groupby("procname")["count"].sum().sort_values(),
        lambda: _w.groupby(["event", "pid_ns"]).agg({"count": ["sum", "mean", "max"]}),
        lambda: _w["count"].describe(),
        lambda: _w["count"].quantile([0.5, 0.95]),
        lambda: _w["event"].value_counts().nlargest(5),
        lambda: _w["procname"].str.contains("a"),
        lambda: _w.pivot_table(index="event", values="count", aggfunc="sum"),
        lambda: _w.sort_values("count").rolling(3, on="bucket_start_s")["k"].mean(),
        lambda: _w.merge(_w, on="event", how="inner").head(1),
        lambda: pd.cut(_w["count"], 3),
        lambda: pd.to_datetime(_w["bucket_start_s"], unit="s"),
        lambda: np.corrcoef(_w["count"], _w["k"]),
        lambda: np.percentile(_w["count"], 90),
        # printing a frame is its own lazy import (pandas.io.formats.string). The first v2
        # smoke run lost a whole snippet to "Too many open files: pandas/io/formats/string.py"
        # right after it had computed the right answer.
        lambda: _w.head(3).to_string(),
        lambda: repr(_w.head(3)),
        lambda: str(_w.groupby("event")["count"].sum().head(3)),
        lambda: _w.head(3).to_dict(),
        lambda: _w.head(3).to_json()):
    try:
        _op()
    except Exception:
        pass

_LINES_FH = open(LINES, "rb")
_lim = _LINES_FH.fileno() + 1
resource.setrlimit(resource.RLIMIT_NOFILE, (_lim, _lim))


def get_lines(event=None, t0=None, t1=None, limit=200):
    """Raw event lines from the sample index, filtered. Returns a list of strings.

    Rewinds the descriptor opened before the limit dropped - wrapping an existing fileobj in
    GzipFile does not open a new one."""
    out = []
    _LINES_FH.seek(0)
    gz = io.TextIOWrapper(gzip.GzipFile(fileobj=_LINES_FH), errors="replace")
    for ln in gz:
        if ln.startswith("#"):
            continue
        p = ln.rstrip(NL).split(TAB, 4)
        if len(p) < 5:
            continue
        try:
            t = float(p[0])
        except ValueError:
            continue
        if event and event not in p[1]:
            continue
        if t0 is not None and t < t0:
            continue
        if t1 is not None and t > t1:
            continue
        out.append(p[4])
        if len(out) >= limit:
            break
    gz.detach()
    return out


_B = __builtins__ if isinstance(__builtins__, dict) else vars(__builtins__)
SAFE = {k: _B[k] for k in (
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float", "format",
    "frozenset", "int", "isinstance", "issubclass", "iter", "len", "list", "map", "max", "min",
    "next", "print", "range", "repr", "reversed", "round", "set", "slice", "sorted", "str",
    "sum", "tuple", "type", "zip", "True", "False", "None", "Exception", "ValueError",
    "KeyError", "IndexError", "TypeError", "ZeroDivisionError", "AttributeError") if k in _B}

# bucket_start_s is SECONDS SINCE MIDNIGHT on the trace clock, not seconds since the start of
# the recording. In the first v2 smoke run the agent assumed 0-based and picked windows of
# 60.0-120.0 on a recording that runs from about 55128; three snippets in a row returned zero
# rows before it worked that out. So hand it the real bounds and the two conversions, and say
# so in the tool description. A sandbox that makes the model rediscover its own coordinate
# system is spending the budget it was added to save.
T0 = float(df["bucket_start_s"].min())
T1 = float(df["bucket_start_s"].max())


def hms(s):
    """Seconds on the trace clock -> 'HH:MM:SS', the format the other tools print."""
    s = float(s)
    return "%02d:%02d:%06.3f" % (int(s // 3600) % 24, int(s // 60) % 60, s % 60)


def secs(t):
    """'HH:MM:SS' (or 'HH:MM:SS.mmm') -> seconds on the trace clock."""
    p = [float(x) for x in str(t).strip().split(":")]
    while len(p) < 3:
        p.insert(0, 0.0)
    return p[0] * 3600 + p[1] * 60 + p[2]


NS = {"__builtins__": SAFE, "df": df, "pd": pd, "np": np, "math": math,
      "statistics": statistics, "collections": collections, "re": re, "json": json,
      "datetime": datetime, "get_lines": get_lines,
      "T0": T0, "T1": T1, "hms": hms, "secs": secs}

sys.stdout.write(json.dumps({"ready": True, "rows": int(len(df))}) + NL)
sys.stdout.flush()
for raw in sys.stdin:
    raw = raw.strip()
    if not raw:
        continue
    req = json.loads(raw)
    buf = io.StringIO()
    real, sys.stdout = sys.stdout, buf
    res = {}
    try:
        exec(compile(req["code"], "<agent>", "exec"), NS)
        res["stdout"] = buf.getvalue()
    except Exception as e:
        res["stdout"] = buf.getvalue()
        res["error"] = "%s: %s" % (type(e).__name__, e)
    finally:
        sys.stdout = real
    sys.stdout.write(json.dumps(res) + NL)
    sys.stdout.flush()
'''


def _readline_timeout(p, timeout):
    """Read one line from the child, or None if it does not answer in time."""
    import selectors
    sel = selectors.DefaultSelector()
    sel.register(p.stdout, selectors.EVENT_READ)
    end = time.time() + timeout
    while time.time() < end:
        if sel.select(max(0.05, min(0.5, end - time.time()))):
            return p.stdout.readline()
        if p.poll() is not None:
            return None
    return None


class Sandbox:
    """One long-lived child per run. Loading a 3M-row index takes seconds, so it is loaded once
    and reused across snippets; a snippet that hangs kills the child and the next call reloads."""

    def __init__(self, run_id, index_root=None):
        self.run_id = run_id
        self.root = index_root or INDEX_ROOT
        self.tsv = os.path.join(self.root, run_id + ".tsv.gz")
        self.lines = os.path.join(self.root, run_id + ".lines.gz")
        self.p = None
        self.rows = None
        self.calls = 0

    def _start(self):
        if self.p is not None and self.p.poll() is None:
            return
        if not os.path.exists(self.tsv):
            raise FileNotFoundError("no count index for %s under %s" % (self.run_id, self.root))
        src = _CHILD.replace("MEM", str(MEM_BYTES))
        self.p = subprocess.Popen(
            [sys.executable, "-c", src, self.tsv, self.lines],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
            # a bare environment: nothing that could point at a proxy or a credential
            env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0", "HOME": "/nonexistent"})
        hello = _readline_timeout(self.p, 180)
        if not hello:
            err = ""
            try:
                self.p.kill()
                err = (self.p.stderr.read() or "")[-600:]
            except Exception:
                pass
            self.p = None
            raise RuntimeError("sandbox failed to load the index. %s" % err)
        self.rows = (json.loads(hello) or {}).get("rows")

    def close(self):
        if self.p is not None:
            try:
                self.p.kill()
            except Exception:
                pass
            self.p = None

    def run(self, code):
        code = textwrap.dedent(code or "").strip()
        if not code:
            return {"error": "empty code"}
        try:
            _scan(code)
        except Rejected as e:
            return {"rejected": True, "error": str(e)}
        self.calls += 1
        t0 = time.time()
        try:
            self._start()
            self.p.stdin.write(json.dumps({"code": code}) + chr(10))
            self.p.stdin.flush()
            line = _readline_timeout(self.p, TIMEOUT_S)
        except Exception as e:                                          # noqa: BLE001
            self.close()
            return {"error": "sandbox failed: %s: %s" % (type(e).__name__, e)}
        if line is None:
            self.close()
            return {"error": "timed out after %.0fs and was killed. The index has about 3 "
                             "million rows; filter before you aggregate."
                             % TIMEOUT_S,
                    "wall_s": round(time.time() - t0, 1)}
        res = json.loads(line)
        out = res.get("stdout") or ""
        d = {"stdout": out[:OUT_CAP], "wall_s": round(time.time() - t0, 1),
             "index_rows": self.rows}
        if len(out) > OUT_CAP:
            d["stdout_truncated"] = ("output cut at %d chars - print a summary, not raw rows"
                                     % OUT_CAP)
        if res.get("error"):
            d["error"] = res["error"]
        if not out.strip() and not res.get("error"):
            d["note"] = "the snippet printed nothing. Use print() to return values."
        return d


TOOL_DEF = {
    "name": "run_python",
    "description": (
        "Write and run Python over this run's kernel-trace index, for any question the other "
        "tools cannot express. Already in scope, no imports needed:\n"
        "df - a pandas DataFrame of the whole recording, about 3 million rows, one per 100 ms "
        "bucket per (event, procname, pid_ns). Columns:\n"
        "  bucket_start_s  float, SECONDS SINCE MIDNIGHT on the trace clock - NOT seconds from "
        "the start of the recording. Use T0 and T1 (the real first and last bucket) and the "
        "helpers hms(seconds) -> 'HH:MM:SS' and secs('HH:MM:SS') -> seconds. Picking a window "
        "like 60 to 120 will match nothing.\n"
        "  event, procname, pid_ns   pid_ns is the container.\n"
        "  count       how many of that event landed in that bucket.\n"
        "  value_sum   the summed PAYLOAD, where one is worth adding up: nanoseconds of CPU "
        "for sched_stat_runtime, bytes for net_dev_xmit and net_if_receive_skb, sectors for "
        "block_rq_issue and block_rq_complete. 0 for every other event. A count says how often "
        "the kernel accounted; value_sum says how much was actually consumed, and for a "
        "throttled or capped container those are very different numbers.\n"
        "get_lines(event=None, t0=None, t1=None, limit=200) - raw event lines as strings with "
        "every kernel field, for anything the columns do not carry: TCP source_port, dest_port "
        "and seq, scheduling priorities, block sectors. One line per bucket per event, so it "
        "shows you the FORM of the data - do not sum over it and call it a total.\n"
        "pd, np, math, statistics, collections, re, json and datetime are in scope too.\n"
        "Use print() - only what you print comes back, so print summaries and not raw rows.\n"
        "There is no filesystem and no network here: this is the index for THIS run and "
        "nothing else."),
    "parameters": {"type": "object", "properties": {
        "code": {"type": "string", "description": "Python to run. Use print() for output."},
        "why": {"type": "string", "description":
                "one line: what question this answers. Recorded with the result."}},
        "required": ["code"]},
}
