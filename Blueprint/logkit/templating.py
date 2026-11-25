"""Turn a log message into a template and a level.

Ported from INQUEST (`C:/workplace/JiraAndLogs/industry-c7`, agent/logs.py @ b161ae8), with the
runtime changes first made in `Blueprint/agent/logtool.py` (16-11-2026):

  - template(): mask the variable parts, so repeats of one statement share a key. A logfmt line
    (go-kit, logrus) keeps its keys and the values of a few keys that name code or outcome
    (caller=, method=, level=); the generic mask would turn caller=logging.go:56 into <v>.
  - level(): 0.5 (debug) to 4 (fatal), from whatever the line carries.
  - is_generic(): timeout / retry / reconnect lines. INQUEST halves their rank: they are usually
    downstream of the cause, not the cause.
  - is_frame(): a stack-trace frame; counted, never a template of its own.

Pure functions, no state. `Blueprint/agent/logtool.py` still holds its own copy for the old
agent; this module is the one to change.
"""
from __future__ import annotations

import re

LEVEL_RE = re.compile(r"\b(FATAL|SEVERE|CRITICAL|PANIC|ERROR|ERR|WARN|WARNING|Warning|INFO|"
                      r"Note|DEBUG|TRACE)\b")
TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2}:\d{2}(?:[.,:]\d+)?(?:Z|[+-]\d{4})?"
                   r"|\b\d{6}\s+\d{1,2}:\d{2}:\d{2}\b"
                   r"|\b\d{1,2}:\d{2}:\d{2}[.,]\d{3}\b")
EXC_RE = re.compile(r"\b[\w.$]*(?:Exception|Error)\b(?::\s*\S.*)?$")
ASSERT_RE = re.compile(r"Assertion\b.*failed|Segmentation fault|got signal \d+"
                       r"|\bSIG(?:SEGV|ABRT|BUS)\b|\bpanic:|fassert\(\) failure")
FRAME_RE = re.compile(r"^\s*(?:at\s+[\w.$<>]+\(|at\s+\S+\s+\(\S+:\d+:\d+\)|#\d+\s+0x[0-9a-f]+"
                      r"|\.\.\.\s*\d+\s+more|Caused by:\s*$|goroutine \d+ \[)")
GENERIC_RE = re.compile(r"time[sd]?\s*out|timeout|retry|retrying|reconnect|heartbeat"
                        r"|health\s*check|backing off|backoff|GC pause|connection reset"
                        r"|circuit breaker|rejecting|unavailable|exhausted", re.I)
WORDY_ERR_RE = re.compile(r"\b(error|failed|failure|refused|exception|panic|fatal|cannot|unable)\b",
                          re.I)
MONGO_SEV_RE = re.compile(r"^\S+ ([FEWID]) [A-Z]+ +\[")
KV_RE = re.compile(r'(?<![\w"])([A-Za-z_][\w.]*)=("(?:[^"\\]|\\.)*"|\S*)')

LEVEL_W = {"FATAL": 4, "SEVERE": 4, "CRITICAL": 4, "PANIC": 4, "F": 4,
           "ERROR": 3, "ERR": 3, "E": 3, "WARN": 2, "WARNING": 2, "Warning": 2, "W": 2,
           "INFO": 1, "Note": 1, "I": 1, "DEBUG": 0.5, "TRACE": 0.5, "D": 0.5}
LOGFMT_LEVEL = {"panic": 4, "fatal": 4, "crit": 4, "error": 3, "err": 3,
                "warning": 2, "warn": 2, "debug": 0.5, "trace": 0.5}
# logfmt keys whose VALUE stays in the template: they name the code path or the outcome.
KEEP_KEYS = frozenset({"caller", "method", "level", "lvl", "component", "transport", "result"})
# logfmt keys dropped from the template: time and per-request values.
DROP_KEYS = frozenset({"ts", "time", "took", "id"})
NULLISH = frozenset({"null", "nil", "<nil>", "none", "", '""', "true", "false"})
MAX_TEMPLATE = 400

_MASKS = (
    # identifier-ish values (a/b, k=v, host:port). First, so it never re-masks the tokens below.
    (re.compile(r"(?<!\S)(?=\S*[_\-/>=@:.])(?=\S*[A-Za-z])\S+(?!\S)"), "<v>"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"\b0x[0-9a-f]+\b", re.I), "<hex>"),
    (re.compile(r"\b[0-9a-f]{16,}\b", re.I), "<hex>"),          # trace, span and object ids
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<ip>"),
    (TS_RE, "<ts>"),
    (re.compile(r"\b\d+(?:[.,]\d+)?\b"), "<n>"),
)
_SPACES = re.compile(r"\s+")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _mask(text: str) -> str:
    for rx, token in _MASKS:
        text = rx.sub(token, text)
    return _SPACES.sub(" ", text).strip()


def is_logfmt(msg: str) -> bool:
    head = msg[:300]
    return len(KV_RE.findall(head)) >= 2 and any(k in head for k in ("caller=", "ts=", "level=", "time="))


def is_frame(msg: str) -> bool:
    return bool(FRAME_RE.search(msg))


def is_generic(msg: str) -> bool:
    return bool(GENERIC_RE.search(msg))


def template(msg: str) -> str:
    """The message with its variable parts masked. Repeats of one statement share it."""
    if not is_logfmt(msg):
        return _mask(msg)[:MAX_TEMPLATE]
    parts = []
    for key, raw in KV_RE.findall(msg):
        if key in DROP_KEYS:
            continue
        value = raw.strip('"')
        if key in KEEP_KEYS:
            # payment's result=true/false is an outcome; catalogue's result=7 is a row count
            parts.append(f"{key}={'<n>' if _NUMBER.fullmatch(value) else value}")
        elif key in ("msg", "message", "err", "error") and value.lower() not in NULLISH:
            parts.append(f"{key}={_mask(value)[:200]}")
        else:
            # a null err= stays err=null, so a failing request and a clean one differ
            parts.append(f"{key}={value if value.lower() in NULLISH else '<v>'}")
    return " ".join(parts)[:MAX_TEMPLATE]


def level(msg: str) -> float:
    """0.5 debug, 1 info, 2 warning, 3 error, 4 fatal."""
    if ASSERT_RE.search(msg):
        return 4.0
    if is_logfmt(msg):
        kv = dict(KV_RE.findall(msg))
        lv = (kv.get("level") or kv.get("lvl") or "").strip('"').lower()
        if lv:
            return float(LOGFMT_LEVEL.get(lv, 1.0))
        for key in ("err", "error", "Error"):
            if key in kv and kv[key].strip('"').lower() not in NULLISH:
                return 3.0
        return 1.0
    m = MONGO_SEV_RE.match(msg)
    if m:
        return float(LEVEL_W[m.group(1)])
    m = LEVEL_RE.search(msg[:200])
    if m:
        return float(LEVEL_W.get(m.group(1), 1.0))
    if EXC_RE.search(msg[:300]) or WORDY_ERR_RE.search(msg[:300]):
        return 3.0
    return 1.0
