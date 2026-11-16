#!/usr/bin/env python3
"""Container logs as agent tools, and the code that printed them.

PORTED FROM INQUEST (C:/workplace/JiraAndLogs/industry-c7, agent/logs.py @ b161ae8). Three ideas
there were measured on 26,544 issues and are kept as they were:

  - template(): mask the variable parts, so repeats of one statement share a key.
  - event ranking: an earlier error ranks above a later one (later errors are usually
    downstream), and generic timeout / retry / reconnect lines are halved.
  - LogIndex: a log line matches a source statement when the statement's constant string
    fragments appear in the line (Xu et al., SOSP 2009, without the static analysis).

What changes here, because INQUEST read log excerpts pasted into Jira and we read whole
per-container docker logs from a run:

  - Lines carry a docker timestamp, so every template gets a first-seen time and per-10 s
    counts. A template that STARTS mid-run is the runtime version of "first error".
  - Sock Shop's formats: go-kit logfmt (caller=file.go:56 method=Get err=null), Spring
    ([orders,traceId,spanId]), Mongo (" I NETWORK"), logrus (level=warning), Node console.log.
    logfmt keys are kept and their values masked; the generic mask would turn
    caller=logging.go:56 into <v> and lose the one field that names the code.
  - The OTel Java agent writes every span to stdout (LoggingSpanExporter) and repeats every
    log line with [scopeInfo: ...]. Those are the span relay, not application logs: they are
    counted and skipped. On carts they are 200 of 206 MB.
  - Go lines name their own source: caller=service.go:98 is matched by file and line before
    any fragment search. Node console.log and single-quoted strings are indexed too; INQUEST
    only knew Java/C++ calls.

THE LEAK RULE (ctf_tool.py, codetool.py): nothing here opens anything in the run directory
except files under logs/. ground_truth.json and verification.* sit beside logs/, never inside.
"""
from __future__ import annotations

import gzip
import os
import re
import threading
from collections import Counter, defaultdict

BUCKET_S = 10
MAX_TEMPLATES = 4000           # per container; beyond it new templates fold into one row
NEW_AFTER_S = 60               # "new" = first seen this long after the run's first log line
LINE_CAP = 400

# ---------------------------------------------------------------------------------------
# from INQUEST logs.py, unchanged
# ---------------------------------------------------------------------------------------
LEVEL_RE = re.compile(
    r"\b(FATAL|SEVERE|CRITICAL|PANIC|ERROR|ERR|WARN|WARNING|Warning|INFO|"
    r"Note|DEBUG|TRACE)\b")
TS_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2}:\d{2}(?:[.,:]\d+)?(?:Z|[+-]\d{4})?"
    r"|\b\d{6}\s+\d{1,2}:\d{2}:\d{2}\b"
    r"|\b\d{1,2}:\d{2}:\d{2}[.,]\d{3}\b")
EXC_RE = re.compile(r"\b[\w.$]*(?:Exception|Error)\b(?::\s*\S.*)?$")
ASSERT_RE = re.compile(r"Assertion\b.*failed|Segmentation fault|got signal \d+"
                       r"|\bSIG(?:SEGV|ABRT|BUS)\b|\bpanic:")
FRAME_LINE_RE = re.compile(
    r"^\s*(?:at\s+[\w.$<>]+\(|at\s+\S+\s+\(\S+:\d+:\d+\)|#\d+\s+0x[0-9a-f]+|\.\.\.\s*\d+\s+more"
    r"|Caused by:\s*$|goroutine \d+ \[)")
GENERIC_RE = re.compile(
    r"time[sd]?\s*out|timeout|retry|retrying|reconnect|heartbeat|health\s*check"
    r"|backing off|backoff|GC pause|connection reset|circuit breaker"
    r"|rejecting|unavailable|exhausted", re.I)
LEVEL_W = {"FATAL": 4, "SEVERE": 4, "CRITICAL": 4, "PANIC": 4, "F": 4,
           "ERROR": 3, "ERR": 3, "E": 3, "WARN": 2, "WARNING": 2, "Warning": 2,
           "W": 2, "INFO": 1, "Note": 1, "I": 1, "DEBUG": 0.5, "TRACE": 0.5, "D": 0.5}
_MASKS = [
    (re.compile(r"(?<!\S)(?=\S*[_\-/>=@:.])(?=\S*[A-Za-z])\S+(?!\S)"), "<v>"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),
     "<uuid>"),
    (re.compile(r"\b0x[0-9a-f]+\b", re.I), "<hex>"),
    (re.compile(r"\b[0-9a-f]{16,}\b", re.I), "<hex>"),          # added: trace/span/mongo ids
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<ip>"),
    (TS_RE, "<ts>"),
    (re.compile(r"\b\d+(?:[.,]\d+)?\b"), "<n>"),
]


def _mask(t: str) -> str:
    for rx, tok in _MASKS:
        t = rx.sub(tok, t)
    return re.sub(r"\s+", " ", t).strip()


# ---------------------------------------------------------------------------------------
# runtime lines
# ---------------------------------------------------------------------------------------
DOCKER_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)Z ")
RELAY_MARKS = ("LoggingSpanExporter", "[scopeInfo:")
KV_RE = re.compile(r'(?<![\w"])([A-Za-z_][\w.]*)=("(?:[^"\\]|\\.)*"|\S*)')
KEEP_KEYS = {"caller", "method", "level", "lvl", "component", "transport", "result"}
NULLISH = {"null", "nil", "<nil>", "none", "", '""', "true", "false"}
SPRING_RE = re.compile(r"\[([\w-]+),([0-9a-f]{16,32}),([0-9a-f]{16}),\w*\]")
MONGO_SEV_RE = re.compile(r"^\S+ ([FEWID]) [A-Z]+ +\[")
TOOK_RE = re.compile(r"\btook=([\w.µ]+)")
DUR_RE = re.compile(r"([\d.]+)(ns|µs|us|ms|s|m|h)")
DUR_MS = {"ns": 1e-6, "µs": 1e-3, "us": 1e-3, "ms": 1.0, "s": 1e3, "m": 6e4, "h": 3.6e6}
METHOD_RE = re.compile(r"\bmethod=(\w+)")


def took_ms(msg: str):
    """go-kit's took= (a Go duration: 1.27ms, 980.3µs, 694ns, 1m2.5s) in milliseconds."""
    m = TOOK_RE.search(msg)
    if not m:
        return None
    parts = DUR_RE.findall(m.group(1))
    return sum(float(n) * DUR_MS[u] for n, u in parts) if parts else None


def _pct(v, q):
    return round(v[min(len(v) - 1, int(q * len(v)))], 3)


WORDY_ERR_RE = re.compile(r"\b(error|failed|failure|refused|exception|panic|fatal|"
                          r"cannot|unable)\b", re.I)


def split_docker(raw: str):
    """(seconds since midnight UTC, message) - the same clock the kernel tools print."""
    m = DOCKER_TS_RE.match(raw)
    if not m:
        return None, raw.rstrip("\n")
    return (int(m.group(2)) * 3600 + int(m.group(3)) * 60 + float(m.group(4)),
            raw[m.end():].rstrip("\n"))


def is_logfmt(msg: str) -> bool:
    return len(KV_RE.findall(msg[:300])) >= 2 and ("caller=" in msg or "ts=" in msg
                                                   or "level=" in msg or "time=" in msg)


def template(msg: str) -> str:
    """Variables masked. logfmt keeps its keys and the values of KEEP_KEYS; an err= that is
    null stays err=null so a failing request and a clean one are different templates."""
    if is_logfmt(msg):
        parts = []
        for k, v in KV_RE.findall(msg):
            if k in ("ts", "time", "took", "id"):
                continue
            vv = v.strip('"')
            if k in KEEP_KEYS:
                parts.append("%s=%s" % (k, vv))
            elif k in ("msg", "message", "err", "error") and vv.lower() not in NULLISH:
                parts.append("%s=%s" % (k, _mask(vv)[:200]))
            else:
                parts.append("%s=%s" % (k, vv if vv.lower() in NULLISH else "<v>"))
        return " ".join(parts)
    return _mask(msg)[:LINE_CAP]


def level(msg: str) -> float:
    if ASSERT_RE.search(msg):
        return 4.0
    if is_logfmt(msg):
        kv = dict(KV_RE.findall(msg))
        lv = (kv.get("level") or kv.get("lvl") or "").strip('"').lower()
        if lv:
            return {"panic": 4, "fatal": 4, "error": 3, "warning": 2, "warn": 2,
                    "debug": 0.5}.get(lv, 1.0)
        for k in ("err", "error", "Error"):
            if k in kv and kv[k].strip('"').lower() not in NULLISH:
                return 3.0
        return 1.0
    m = MONGO_SEV_RE.match(msg)
    if m:
        return LEVEL_W[m.group(1)]
    m = LEVEL_RE.search(msg[:200])
    if m:
        return LEVEL_W.get(m.group(1), 1.0)
    if EXC_RE.search(msg[:300]) or WORDY_ERR_RE.search(msg[:300]):
        return 3.0
    return 1.0


def _hms(s):
    if s is None:
        return None
    s = float(s)
    return "%02d:%02d:%06.3f" % (int(s // 3600) % 24, int(s // 60) % 60, s % 60)


def _secs(t):
    if t in (None, ""):
        return None
    p = [float(x) for x in str(t).strip().split(":")]
    while len(p) < 3:
        p.insert(0, 0.0)
    return p[0] * 3600 + p[1] * 60 + p[2]


def _container(fname: str) -> str:
    """docker-compose_front-end_1.log -> front-end"""
    n = re.sub(r"\.log(\.gz)?$", "", fname)
    n = re.sub(r"^docker-compose[_-]", "", n)
    return re.sub(r"[_-]\d+$", "", n)


def _open(p):
    return gzip.open(p, "rt", errors="replace") if p.endswith(".gz") else \
        open(p, errors="replace")


class RunLogs:
    """Every container log of one run, read once into templates with per-10 s counts."""

    def __init__(self, run_dir: str):
        self.dir = os.path.join(run_dir, "logs")
        self.files = {}
        if os.path.isdir(self.dir):
            for f in sorted(os.listdir(self.dir)):
                if re.search(r"\.log(\.gz)?$", f):
                    self.files[_container(f)] = os.path.join(self.dir, f)
        self.c = {}                     # container -> stats
        for name, p in self.files.items():
            self.c[name] = self._read(p)
        # the RUN's first line, not the container's: a quiet container whose first line ever is
        # an error mid-run (edge-router on code_event_loop_block: 458 warnings from 03:59:08)
        # is the newest thing in the run, and measuring from its own start hid it
        self.t0 = min((st["t0"] for st in self.c.values() if st["t0"] is not None),
                      default=None)

    def _read(self, path):
        st = {"lines": 0, "relay": 0, "t0": None, "t1": None, "tpl": {}, "errors": 0,
              "took": defaultdict(lambda: defaultdict(list))}      # method -> bucket -> [ms]
        tpl = st["tpl"]
        with _open(path) as fh:
            for raw in fh:
                t, msg = split_docker(raw)
                if any(m in msg for m in RELAY_MARKS):
                    st["relay"] += 1
                    continue
                if not msg.strip() or FRAME_LINE_RE.search(msg):
                    continue
                st["lines"] += 1
                if t is not None:
                    st["t0"] = t if st["t0"] is None else st["t0"]
                    st["t1"] = t
                if t is not None and "took=" in msg:
                    ms = took_ms(msg)
                    if ms is not None:
                        mm = METHOD_RE.search(msg)
                        st["took"][mm.group(1) if mm else "?"][
                            int(t // BUCKET_S) * BUCKET_S].append(ms)
                key = template(msg)
                g = tpl.get(key)
                if g is None:
                    if len(tpl) >= MAX_TEMPLATES:
                        # ponytail: fold overflow into one row; raise MAX_TEMPLATES if it fills
                        key = "<other templates>"
                        g = tpl.get(key)
                    if g is None:
                        g = tpl[key] = {"line": msg[:LINE_CAP], "first": t, "last": t,
                                        "level": level(msg), "count": 0,
                                        "generic": bool(GENERIC_RE.search(msg)),
                                        "buckets": Counter()}
                g["count"] += 1
                g["last"] = t if t is not None else g["last"]
                if t is not None:
                    g["buckets"][int(t // BUCKET_S) * BUCKET_S] += 1
                if g["level"] >= 3:
                    st["errors"] += 1
        return st

    # -- tools ---------------------------------------------------------------------
    def overview(self) -> dict:
        if not self.files:
            return {"error": "this run has no logs/ directory"}
        rows = []
        for name, st in self.c.items():
            top = sorted(st["tpl"].values(), key=lambda g: -g["count"])[:3]
            rows.append({"container": name, "lines": st["lines"],
                         "span_relay_lines_skipped": st["relay"],
                         "templates": len(st["tpl"]), "error_level_lines": st["errors"],
                         "first": _hms(st["t0"]), "last": _hms(st["t1"]),
                         "top_templates": [{"count": g["count"], "line": g["line"][:160]}
                                           for g in top]})
        return {"containers": rows,
                "note": "times are HH:MM:SS UTC, the same clock as the kernel tools"}

    def events(self, container=None, begin=None, end=None, k=12) -> dict:
        """INQUEST's ranking over templates, plus novelty: a template whose first line comes
        well after its container started is new behaviour, and ranks up."""
        b, e = _secs(begin), _secs(end)
        cands = []
        for name, st in self.c.items():
            if container and container != name:
                continue
            for key, g in st["tpl"].items():
                if b is None and e is None:
                    n = g["count"]
                else:
                    n = sum(c for t, c in g["buckets"].items()
                            if (b is None or t + BUCKET_S > b) and (e is None or t <= e))
                if not n:
                    continue
                new = (g["first"] is not None and self.t0 is not None
                       and g["first"] - self.t0 > NEW_AFTER_S)
                cands.append((name, key, g, n, new))
        if not cands:
            return {"events": [], "note": "no log lines in that container/window"}
        errs = sorted((c for c in cands if c[2]["level"] >= 3),
                      key=lambda c: c[2]["first"] if c[2]["first"] is not None else 1e9)
        bonus = {id(c[2]): 1.5 / (1 + r) for r, c in enumerate(errs)}
        scored = []
        for c in cands:
            g = c[2]
            s = g["level"] + bonus.get(id(g), 0.0) + (1.5 if c[4] else 0.0)
            if g["generic"]:
                s *= 0.5
            scored.append((round(s, 3), c))
        top = sorted(scored, key=lambda x: (-x[0], x[1][2]["first"] or 0))[:max(1, int(k))]
        top.sort(key=lambda x: x[1][2]["first"] or 0)
        return {"window": [begin, end], "events": [
            {"id": "E%d" % (i + 1), "container": c[0], "line": c[2]["line"],
             "template": c[1][:200], "count_in_window": c[3], "count_total": c[2]["count"],
             "first_seen": _hms(c[2]["first"]), "last_seen": _hms(c[2]["last"]),
             "level": c[2]["level"], "new": c[4], "generic": c[2]["generic"], "score": s}
            for i, (s, c) in enumerate(top)]}

    def latency(self, container=None, method=None) -> dict:
        """Per container and method: requests and p50/p95/max of took= per 10 s. This is the
        log signal for a fault that prints no error - the request simply takes longer."""
        rows = []
        for name, st in self.c.items():
            if container and container != name:
                continue
            for meth, buckets in sorted(st["took"].items()):
                if method and method != meth:
                    continue
                allv = sorted(v for b in buckets.values() for v in b)
                rows.append({"container": name, "method": meth, "requests": len(allv),
                             "p50_ms_whole_run": _pct(allv, 0.5),
                             "per_10s": [{"t": _hms(b)[:8], "n": len(v),
                                          "p50_ms": _pct(sorted(v), 0.5),
                                          "p95_ms": _pct(sorted(v), 0.95),
                                          "max_ms": round(max(v), 3)}
                                         for b, v in sorted(buckets.items())]})
        if not rows:
            return {"rows": [], "note": "no took= field in these logs (only go-kit services "
                                        "print one: catalogue, user, payment)"}
        return {"rows": rows, "note": "took is the handler's own time as the service logged it"}

    def search(self, pattern, container=None, begin=None, end=None, limit=30) -> dict:
        """Regex over the raw lines: counts per 10 s bucket per container, and sample lines."""
        rx = re.compile(pattern, re.I)
        b, e = _secs(begin), _secs(end)
        series, samples, total = defaultdict(Counter), [], 0
        for name, p in self.files.items():
            if container and container != name:
                continue
            with _open(p) as fh:
                for raw in fh:
                    t, msg = split_docker(raw)
                    if (b is not None and t is not None and t < b) or \
                       (e is not None and t is not None and t > e):
                        continue
                    if any(m in msg for m in RELAY_MARKS) or not rx.search(msg):
                        continue
                    total += 1
                    if t is not None:
                        series[name][_hms(int(t // BUCKET_S) * BUCKET_S)[:8]] += 1
                    if len(samples) < int(limit):
                        samples.append({"container": name, "t": _hms(t), "line": msg[:LINE_CAP]})
        return {"pattern": pattern, "matches": total,
                "per_10s": {n: dict(sorted(s.items())) for n, s in series.items()},
                "samples": samples}


# ---------------------------------------------------------------------------------------
# log line -> source statement (INQUEST LogIndex, over a connected CodeRepo, not git grep)
# ---------------------------------------------------------------------------------------
CODE_EXT = (".go", ".java", ".js", ".ts", ".py", ".scala", ".kt", ".c", ".cc", ".cpp", ".h")
CALL_RE = re.compile(
    r"\b(?:log|LOG|Log|logger|Logger|LOGGER|_log|_logger|log_|logger_)\w*\s*"
    r"(?:\.|->|::)\s*(?:trace|debug|info|warn|warning|error|fatal|severe)\w*\s*\("
    r"|\.Log\s*\(|\b(?:log\.(?:Print|Fatal|Panic)\w*|fmt\.Errorf|errors\.New)\s*\("  # Go
    r"|\bconsole\.(?:log|error|warn|info)\s*\(|\bnew\s+Error\s*\("                  # Node
    r"|\bthrow\s+new\s+\w+|\bthrow\s+\w+\s*\(|\b(?:error|warn|fatal|panic)\s*\("
    r"|\braise\s+\w+")
STR_RE = re.compile(r'"((?:[^"\\\n]|\\.)*)"' r"|'((?:[^'\\\n]|\\.)*)'" r"|`([^`\n]*)`")
FMT_RE = re.compile(r"%[-+ #0]*\d*(?:\.\d+)?(?:hh|h|ll|l|z|j|t|L)?[diouxXeEfgGcspnvqTw]"
                    r"|\{\d*\}|\$\{[^}]*\}|\$\w+|\\[ntr]")
WORD_RE = re.compile(r"[A-Za-z]{4,}")
FUNC_RE = re.compile(r"^\s*func\s|\bfunction\b|^\s*def\s|=>\s*\{"
                     r"|^\s*(?:public|private|protected|static)[^;=]*\([^;]*\)\s*(?:throws[^{]*)?\{")
CALLER_RE = re.compile(r"\bcaller=([\w./-]+\.\w+):(\d+)")
MAX_DF = 1500
MAX_CODE_LINE = 500


def fragments(code_line: str) -> list[str]:
    frags = []
    for groups in STR_RE.findall(code_line):
        lit = next((g for g in groups if g), "")
        for f in FMT_RE.split(lit):
            f = f.strip(" :=,;.'()[]")
            if sum(c.isalpha() for c in f) >= 3:
                frags.append(f)
    return frags


class LogIndex:
    """Logging calls and error constructors of one connected source tree."""

    def __init__(self, repo):
        self.repo = repo                # coderepo.CodeRepo: its jail and denylist apply
        self.stmts, self.by_word = [], defaultdict(list)
        self.lines_of = {}              # rel path -> list of lines (for caller= and functions)
        from coderepo import SKIP_DIRS, MAX_FILE_BYTES
        for dirpath, dirnames, filenames in os.walk(repo.root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and d != "vendor")
            for f in filenames:
                if not f.endswith(CODE_EXT) or repo._denied(f):
                    continue
                p = os.path.join(dirpath, f)
                try:
                    if os.path.getsize(p) > MAX_FILE_BYTES:
                        continue
                    lines = open(p, errors="replace").read().splitlines()
                except OSError:
                    continue
                rel = os.path.relpath(p, repo.root).replace(os.sep, "/")
                self.lines_of[rel] = lines
                for i, text in enumerate(lines):
                    # a minified bundle is one line of 100 kB; it is not a logging statement,
                    # and the string regex backtracks on it for minutes
                    if len(text) > MAX_CODE_LINE or not CALL_RE.search(text):
                        continue
                    frags = fragments(text)
                    if not frags and not text.rstrip().endswith((";", ")")):
                        frags = fragments(" ".join(lines[i + 1:i + 3]))   # message on next line
                    if not frags:
                        continue
                    sid = len(self.stmts)
                    self.stmts.append({"file": rel, "line": i + 1, "code": text.strip()[:200],
                                       "frags": frags, "total": sum(len(x) for x in frags)})
                    for w in {w.lower() for x in frags for w in WORD_RE.findall(x)}:
                        self.by_word[w].append(sid)

    def function_at(self, rel, lno):
        """The nearest function header above a line. ponytail: no brace matching, so a nested
        closure reports the closure; use a parser (tree-sitter) if that misleads."""
        lines = self.lines_of.get(rel) or []
        for i in range(min(lno, len(lines)) - 1, -1, -1):
            if FUNC_RE.search(lines[i]):
                return lines[i].strip()[:160]
        return "(file scope)"

    def _hit(self, rel, lno, how, **kw):
        lines = self.lines_of.get(rel) or []
        code = lines[lno - 1].strip()[:200] if 0 < lno <= len(lines) else ""
        return {"file": rel, "line": lno, "function": self.function_at(rel, lno),
                "code": code, "how": how, **kw}

    def match(self, line: str, k: int = 5) -> list[dict]:
        out = []
        m = CALLER_RE.search(line)
        if m:       # go-kit prints its own call site
            name, lno = m.group(1).rsplit("/", 1)[-1], int(m.group(2))
            for rel in self.lines_of:
                if rel == m.group(1) or rel.endswith("/" + name) or rel == name:
                    out.append(self._hit(rel, lno, "caller= field printed by the logger"))
        low = line.lower()
        cand = set()
        for w in set(WORD_RE.findall(low)):
            ids = self.by_word.get(w)
            if ids and len(ids) <= MAX_DF:
                cand.update(ids)
        classes = {c.lower() for c in re.findall(r"\b(?:[a-z]\w*\.)+([A-Z]\w+)\b", line)}
        scored = []
        for sid in cand:
            s = self.stmts[sid]
            cov = sum(len(f) for f in s["frags"] if f.lower() in low)
            frac = cov / s["total"]
            if cov < 8 or (cov < 15 and frac < 1.0):
                continue
            stem = s["file"].rsplit("/", 1)[-1].split(".")[0].lower()
            scored.append((cov * (0.5 + frac) + (20 if stem in classes else 0), frac, sid))
        seen = {(h["file"], h["line"]) for h in out}
        for score, frac, sid in sorted(scored, key=lambda x: -x[0]):
            s = self.stmts[sid]
            if (s["file"], s["line"]) in seen:
                continue
            seen.add((s["file"], s["line"]))
            out.append(self._hit(s["file"], s["line"], "message text matches the statement",
                                 coverage=round(frac, 2), score=round(score, 1)))
            if len(out) >= k:
                break
        return out[:k]


# ---------------------------------------------------------------------------------------
TOOL_DEFS = [
    {"name": "log_overview",
     "description": "Container logs of this run: per container, how many application log lines, "
                    "how many distinct message templates, how many error-level lines, the first "
                    "and last timestamp (HH:MM:SS UTC, the kernel tools' clock) and the 3 most "
                    "common templates. Span-relay lines the OTel agent writes to stdout are "
                    "skipped and only counted. Start here.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "log_events",
     "description": "The most failure-relevant DISTINCT log events, one row per message "
                    "template, ranked: errors above warnings above info, the EARLIEST error "
                    "above later ones (later errors are usually downstream), templates that "
                    "first appear mid-run ('new': true) ranked up, and generic timeout / retry "
                    "/ reconnect lines halved. Optionally limited to one container and a "
                    "window. Returned in time order with first_seen, count_in_window and one "
                    "verbatim example line. Compare a window against the time before it to see "
                    "what CHANGED; an error present from the first second is usually the "
                    "baseline, not the fault.",
     "parameters": {"type": "object", "properties": {
         "container": {"type": "string", "description": "e.g. catalogue, front-end (optional)"},
         "begin": {"type": "string", "description": "start 'HH:MM:SS' UTC (optional)"},
         "end": {"type": "string", "description": "end 'HH:MM:SS' UTC (optional)"},
         "k": {"type": "integer", "description": "how many events, default 12"}},
         "required": []}},
    {"name": "log_search",
     "description": "Regex (case-insensitive) over the raw log lines: matches per 10 s bucket "
                    "per container, plus sample lines. Use it to time a message's onset, or to "
                    "follow one request: Spring services (orders, carts, shipping) print "
                    "[service,traceId,spanId] in each line, and go-kit services print "
                    "caller=file.go:line.",
     "parameters": {"type": "object", "properties": {
         "pattern": {"type": "string"},
         "container": {"type": "string"},
         "begin": {"type": "string", "description": "'HH:MM:SS' UTC"},
         "end": {"type": "string", "description": "'HH:MM:SS' UTC"},
         "limit": {"type": "integer", "description": "sample lines, default 30"}},
         "required": ["pattern"]}},
]
TOOL_DEFS.append(
    {"name": "log_latency",
     "description": "Request latency as the services themselves logged it: go-kit services "
                    "(catalogue, user, payment) print took=<duration> on every request line. "
                    "Returns, per container and method, the request count and p50 / p95 / max "
                    "in ms for every 10 s of the run. A fault that prints NO error still shows "
                    "here as a jump in p50 or a drop in n. A method whose latency jumps while "
                    "other methods of the SAME service stay flat points inside that method.",
     "parameters": {"type": "object", "properties": {
         "container": {"type": "string"}, "method": {"type": "string"}}, "required": []}})
LOG_TO_CODE_DEF = {
    "name": "log_to_code",
    "description": "Find the source statement that printed a log line, in the connected code "
                   "repository: file, line, the statement, and the enclosing function. Go lines "
                   "with caller=file.go:N are matched exactly; others by the constant text of "
                   "the logging call. The statement that PRINTED an error is often not where "
                   "the fault is - read its function and callers with code_read/code_grep "
                   "before naming a culprit.",
    "parameters": {"type": "object", "properties": {
        "line": {"type": "string", "description": "one log line, verbatim"},
        "k": {"type": "integer", "description": "candidates, default 5"}},
        "required": ["line"]}}
TOOL_NAMES = {t["name"] for t in TOOL_DEFS} | {LOG_TO_CODE_DEF["name"]}


class LogTools:
    """Run-scoped: the run's logs (read on first use) and, when a repo is connected, its
    statement index (built on first log_to_code)."""

    def __init__(self, run_dir, repo=None):
        self.run_dir, self.repo = run_dir, repo
        self._logs = self._idx = None
        self._lock = threading.Lock()

    def call(self, name, args):
        # ponytail: one lock for everything - 4 workers share this, and the lazy builds must
        # run once. A log_search is ~3 s on a 250 MB run; lock only the builds if that queues.
        with self._lock:
            return self._call(name, args)

    def _call(self, name, args):
        args = args or {}
        try:
            if name == "log_to_code":
                if self.repo is None:
                    return {"error": "no code repository is connected"}
                if self._idx is None:
                    self._idx = LogIndex(self.repo)
                hits = self._idx.match(args.get("line") or "", int(args.get("k") or 5))
                return {"candidates": hits} if hits else {
                    "candidates": [], "note": "no statement's text appears in that line"}
            if self._logs is None:
                self._logs = RunLogs(self.run_dir)
            if name == "log_overview":
                return self._logs.overview()
            if name == "log_latency":
                return self._logs.latency(args.get("container"), args.get("method"))
            if name == "log_events":
                return self._logs.events(args.get("container"), args.get("begin"),
                                         args.get("end"), int(args.get("k") or 12))
            if name == "log_search":
                return self._logs.search(args.get("pattern") or ".", args.get("container"),
                                         args.get("begin"), args.get("end"),
                                         int(args.get("limit") or 30))
            return {"error": "unknown log tool %r" % name}
        except (re.error, ValueError, OSError) as e:
            return {"error": "%s: %s" % (type(e).__name__, e)}


def _selfcheck() -> None:
    import tempfile
    gk = ("2026-09-05T15:18:46.942215124Z ts=2026-09-05T15:18:46.94Z caller=logging.go:56 "
          "method=Get id=03fe sock=03fe err=null took=1.2ms\n")
    gk_err = ("2026-09-05T15:21:00.000000000Z ts=2026-09-05T15:21:00Z caller=logging.go:56 "
              "method=Get id=03fe sock=03fe err=\"database connection refused\" took=3s\n")
    relay = ("2026-09-05T15:18:46.4Z [otel.javaagent 2026-09-05 15:18:46:458 +0000] INFO "
             "io.opentelemetry.exporter.logging.LoggingSpanExporter - 'find' : abc\n")
    assert template(split_docker(gk)[1]) == "caller=logging.go:56 method=Get sock=<v> err=null"
    assert level(split_docker(gk)[1]) == 1.0 and level(split_docker(gk_err)[1]) == 3.0
    assert level("2026-09-05T15:19:47.900+0000 E NETWORK  [thread1] x") == 3
    assert level('time="x" level=warning msg="Error forwarding"') == 2
    assert fragments("console.log('Item deleted with status: ' + r.statusCode);") == \
        ["Item deleted with status"]
    assert fragments('s.logger.Log("database error", err)') == ["database error"]
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "run", "logs"))
        os.makedirs(os.path.join(td, "src"))
        with open(os.path.join(td, "run", "logs", "docker-compose_catalogue_1.log"), "w") as f:
            f.write(gk * 50 + relay * 20 + gk_err * 3)
        with open(os.path.join(td, "run", "ground_truth.json"), "w") as f:
            f.write('{"fault": "secret"}')
        with open(os.path.join(td, "src", "logging.go"), "w") as f:
            f.write("package main\n" + "\n" * 52 +          # so the Log( call is line 56
                    "func (mw loggingMiddleware) Get(id string) (Sock, error) {\n"
                    "\tdefer func(begin time.Time) {\n\t\tmw.logger.Log(\n"
                    '\t\t\t"method", "Get",\n')
        lt = LogTools(os.path.join(td, "run"))
        ov = lt.call("log_overview", {})["containers"][0]
        assert ov["container"] == "catalogue" and ov["span_relay_lines_skipped"] == 20, ov
        assert ov["templates"] == 2 and ov["error_level_lines"] == 3, ov
        ev = lt.call("log_events", {"k": 1})["events"]
        assert ev[0]["level"] == 3 and ev[0]["new"] is True, ev       # the mid-run error wins
        assert lt.call("log_search", {"pattern": "refused"})["matches"] == 3
        assert took_ms("took=1m2.5s") == 62500 and abs(took_ms("took=980.311µs") - 0.980311) < 1e-9
        lat = lt.call("log_latency", {})["rows"][0]
        assert lat["method"] == "Get" and lat["requests"] == 53, lat
        assert lat["per_10s"][-1]["p50_ms"] == 3000.0, lat
        assert "secret" not in repr(lt.call("log_search", {"pattern": "fault"}))
        import coderepo
        lt.repo = coderepo.CodeRepo(os.path.join(td, "src"))
        hit = lt.call("log_to_code", {"line": split_docker(gk_err)[1]})["candidates"][0]
        assert hit["file"] == "logging.go" and hit["line"] == 56 and "Log(" in hit["code"], hit
        assert hit["function"].startswith("func (mw loggingMiddleware) Get"), hit
    print("logtool selfcheck ok")


if __name__ == "__main__":
    _selfcheck()
