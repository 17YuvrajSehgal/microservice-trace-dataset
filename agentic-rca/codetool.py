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
import ast, json, os, subprocess, sys, textwrap, threading, time

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


# Modules already loaded in the sandbox namespace. Importing one of these is a no-op that
# binds a name the snippet could have used anyway; importing anything else is refused.
IN_SCOPE = {"pandas", "numpy", "math", "statistics", "collections", "re", "json", "datetime",
            "itertools", "functools", "operator", "heapq", "bisect", "decimal", "fractions"}


def _import_msg(name):
    return ("rejected: cannot import %r. Available without importing: pandas as pd, numpy as "
            "np, math, statistics, collections, re, json, datetime, itertools, functools, "
            "operator, heapq, bisect. There is no filesystem and no network here." % name)


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
        # Importing something ALREADY in scope is allowed. Blanket-rejecting imports was the
        # single biggest cause of failure in the first real run: 71 of 169 snippets, 42%, were
        # thrown out for writing `import pandas as pd` - a habit the model has regardless of
        # being told pd is already bound. There is nothing to gain by refusing, because
        # `__import__` here only serves sys.modules: no new module loads, no file opens, and
        # the descriptor cap would refuse one anyway. Anything NOT in this set is still
        # rejected, and with a message that says what is available.
        if isinstance(node, ast.Import):
            for al in node.names:
                root = al.name.partition(".")[0]
                if root not in IN_SCOPE:
                    raise Rejected(_import_msg(al.name))
            continue
        if isinstance(node, ast.ImportFrom):
            root = (node.module or "").partition(".")[0]
            if node.level or root not in IN_SCOPE:
                raise Rejected(_import_msg(node.module or "."))
            continue
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise Rejected("rejected: dunder attribute %r is not allowed." % node.attr)
        if isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            raise Rejected("rejected: %r is not available in this sandbox." % node.id)


# --------------------------------------------------------------------------------------
# The child. Its own process so a runaway snippet can be killed without taking the agent with
# it, and so the kernel limits apply to it alone. MEM is substituted before launch.
# --------------------------------------------------------------------------------------
_CHILD = '''
import json, sys, os, gzip, io, math, statistics, collections, re, datetime

# The kernel limits below are the strongest barrier this sandbox has, and they exist only on
# POSIX. On Windows `resource` is absent, so they are skipped and the AST scan plus the
# builtins whitelist carry the weight alone - which is weaker, because pandas and numpy do
# their own file I/O and the descriptor cap is what stops that.
#
# The difference is REPORTED, not hidden: every result carries `limits_enforced`, and the demo
# prints it. Research runs are on Linux, where all of it applies.
LIMITS = True
try:
    import resource
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))      # cannot write one byte
    resource.setrlimit(resource.RLIMIT_AS, (MEM, MEM))
except Exception:
    LIMITS = False
import pandas as pd, numpy as np

TAB = chr(9)
NL = chr(10)
TSV, LINES = sys.argv[1], sys.argv[2]
_COLS = ["bucket_start_s", "event", "procname", "pid_ns", "count", "value_sum"]
# NO comment="#" HERE. pandas treats "#" as starting a comment ANYWHERE in a line, not just in
# column 0, and the JVM names its garbage-collector threads "GC Thread#0" .. "GC Thread#12".
# On tt_deadlock_..._r1 that is 372,821 rows: each was truncated at the "#", leaving 3 fields
# instead of 6, so pid_ns came back as float64 full of NaN and the missing counts dropped out
# of every sum. run_python under-reported sched_switch by 2% against query_ctf on Train Ticket
# and matched exactly on Sock Shop, which has no "#" in any procname - a wrong number on Java
# applications only, and silent. The header is the one line starting with "#", so skip it by
# position instead.
_ncol = len(pd.read_csv(TSV, sep=TAB, compression="gzip", nrows=1,
                        skiprows=1, header=None).columns)
df = pd.read_csv(TSV, sep=TAB, compression="gzip", names=_COLS[:_ncol], skiprows=1)
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
        lambda: _w.head(3).to_json(),
        # printing a dtype is what exposed the missing __import__
        lambda: str(_w['count'].dtype) + str(_w.dtypes),
        lambda: _w['count'].isna().sum() + _w['count'].nunique()):
    try:
        _op()
    except Exception:
        pass

_LINES_FH = open(LINES, "rb")

# PORTABLE BARRIER, and on Windows the only one that stops this.
#
# pandas and numpy do their own file I/O, so removing `open` from the snippet's builtins is
# not enough: pd.read_json on a path built up from fragments reads whatever it likes. On Linux
# the descriptor cap below refuses it at the kernel. On Windows there is no such cap, and the
# adversarial test confirmed the leak - a built path plus pd.read_json returned ground truth.
#
# So wrap the real `open` for the whole child: only the two index files may be opened, by
# anyone, including library internals. pandas routes its readers through builtins.open, so
# this catches them. It is checked by resolved absolute path, not by the string passed in.
_ALLOWED = {os.path.realpath(TSV), os.path.realpath(LINES)}
_real_open = open


def _guarded_open(file, *a, **k):
    try:
        rp = os.path.realpath(file)
    except TypeError:
        rp = None                       # a file descriptor, not a path - already ours
    if rp is not None and rp not in _ALLOWED:
        raise PermissionError(
            "this sandbox may read only its own trace index, not %r. It has no filesystem: "
            "the data is already in `df` and get_lines()." % str(file)[:120])
    return _real_open(file, *a, **k)


import builtins as _b
_b.open = _guarded_open
io.open = _guarded_open

if LIMITS:
    try:
        _lim = _LINES_FH.fileno() + 1
        resource.setrlimit(resource.RLIMIT_NOFILE, (_lim, _lim))
    except Exception:
        LIMITS = False


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


def _already_imported(name, globals=None, locals=None, fromlist=(), level=0):
    """__import__ restricted to modules that are ALREADY loaded.

    Leaving __import__ out of builtins entirely looked safe and was not usable: numpy and
    pandas import lazily from inside ordinary operations, and Python resolves that through
    builtins, so `print(df['pid_ns'].dtype)` died with `KeyError: '__import__'`. That is a
    baffling error to hand an agent for a correct line of pandas, and it would read as "the
    tool is broken" rather than "ask differently".

    Serving only sys.modules keeps the barrier: nothing new is loaded, so no file is opened,
    and the descriptor cap below would refuse anyway. A snippet cannot call this directly -
    the AST scan rejects the name `__import__`, and getattr and dunder attributes are rejected
    too - so the only callers are library internals that were going to succeed regardless.
    """
    mod = sys.modules.get(name)
    if mod is None:
        raise ImportError(
            "%r is not available in this sandbox. pandas as pd, numpy as np, math, "
            "statistics, collections, re, json and datetime are already in scope." % name)
    if fromlist:
        return mod
    return sys.modules.get(name.partition(".")[0], mod)


SAFE["__import__"] = _already_imported

import itertools, functools, operator, heapq, bisect

NS = {"__builtins__": SAFE, "df": df, "pd": pd, "np": np, "math": math,
      "statistics": statistics, "collections": collections, "re": re, "json": json,
      "datetime": datetime, "get_lines": get_lines, "itertools": itertools,
      "functools": functools, "operator": operator, "heapq": heapq, "bisect": bisect,
      "Counter": collections.Counter, "defaultdict": collections.defaultdict,
      "T0": T0, "T1": T1, "hms": hms, "secs": secs}

sys.stdout.write(json.dumps({"ready": True, "rows": int(len(df)),
                             "limits": bool(LIMITS)}) + NL)
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
    """Read one line from the child, or None if it does not answer in time.

    A reader thread rather than selectors: selectors cannot watch a pipe on Windows - it
    treats the handle as a socket and raises WinError 10093 - and this behaves the same on
    both. The thread is a daemon, so a child that never answers cannot hold the process open.
    """
    import queue
    q = getattr(p, "_lineq", None)
    if q is None:
        q = queue.Queue()
        p._lineq = q

        def pump(fh, out):
            try:
                for ln in iter(fh.readline, ""):
                    out.put(ln)
            except Exception:                                           # noqa: BLE001
                pass
            out.put(None)

        t = threading.Thread(target=pump, args=(p.stdout, q), daemon=True)
        t.start()
        p._pump = t
    try:
        return q.get(timeout=timeout)
    except queue.Empty:
        return None


# Anything that looks like a credential, and the proxy variables that could route a request
# somewhere. Substring match, deliberately broad - a false positive costs nothing here.
_SECRET = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "AUTH", "SESSION",
           "PROXY", "AWS_", "AZURE_", "OPENAI", "ANTHROPIC", "GEMINI")


def _child_env():
    """The child's environment: the parent's, minus anything sensitive, plus thread pins.

    Replacing the environment outright looked safer and broke the sandbox on Windows - the
    child could not find its own site-packages and died with ModuleNotFoundError on pandas.
    Filtering achieves the same thing (no credential reaches a snippet) and runs everywhere.

    The thread pins are not tuning. Measured: 64 of 169 snippets in the first real run died
    with "libgomp: Thread creation failed" because eight parallel cells each started a child
    that sized an OpenMP pool to a 192-core shared login node. Those cells ran with no working
    code tool at all, silently. This work is a groupby over a few million rows; one thread is
    plenty.
    """
    env = {k: v for k, v in os.environ.items()
           if not any(w in k.upper() for w in _SECRET)}
    env.update({"PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
                "VECLIB_MAXIMUM_THREADS": "1"})
    return env


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
        self.limits = None
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
            env=_child_env())
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
        _h = json.loads(hello) or {}
        self.rows = _h.get("rows")
        self.limits = bool(_h.get("limits"))

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
             "index_rows": self.rows, "limits_enforced": self.limits}
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
