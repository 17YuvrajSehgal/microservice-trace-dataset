#!/usr/bin/env python3
"""One decode, many consumers.

WHY THIS EXISTS
---------------
Every analysis script opened its own `babeltrace2 | grep` over the same trace. Measured on a
real StrataTrace L0 kernel trace (14 GB decompressed, 258M events, Sock Shop anomaly_cpu r1):

    full pass, decode + format text      361 s
    full pass, decode ONLY (-o dummy)    101 s     <- text formatting is 72% of the cost
    one 60 s window (--begin/--end)      111 s

Ten scripts, each scanning a 55 s baseline and a 60 s incident window, is **20 decodes of one
file**. The seven scripts a full blueprint battery uses cost ~26 min per run, and almost all of
it is re-decoding bytes we already decoded.

Two things make sharing possible:

  * every script uses the SAME two windows (baseline 55 s, incident 60 s - verified: all ten
    declare identical argparse defaults), so one extraction serves all of them;
  * the scripts all consume the same thing - an iterator of babeltrace's text lines - so a
    shared reader can be swapped in without touching a single line of parsing logic.

`--begin/--end` is worth keeping even so: the 60 s window costs 111 s against 361 s for the
whole trace, so the trimmer does cut work. It does NOT seek, though - it decodes and then
discards, which is why a 23%-of-events window still costs 31% of the time.

HOW IT IS USED
--------------
    with ctf_stream.stream(ctf, begin, end, "sched_switch", family="sched") as src:
        for line in src:
            ...

`pattern` stays exactly what the script always grepped for, in BOTH paths. The cache holds a
family superset (all `sched_*`, all `net_*`, ...) and the script's own grep still runs on top,
so a script cannot see one line more or fewer than it did before. That is what makes this
safe to verify by diffing output JSON.

Set `CTF_CACHE_DIR` to a directory built by `ctf_extract.py` to use the shared extraction.
Unset, or a cache miss, falls back to decoding - so nothing breaks when the cache is absent.
"""
from __future__ import annotations
import contextlib, os, subprocess

BT2 = os.environ.get("BT2", "/scratch/yuvraj17/stratatrace/tools/bt21.sh")

# One family per grep pattern actually used by our scripts, each a superset of what any single
# consumer needs. Counts are from the 4M-event sample of the trace above - they say which
# families are worth sharing and how big the cache will be.
#
#   family    consumers                                             share of events
#   sched     oncpu_share, runqueue_delay                                    16.1%
#   net       net_loss_signature, endpoint_latency, flow_activity,            7.2%
#             socket_peer_wait
#   syscall   blocking_syscall                                              40.9%
#   block     block_io_signature                                             0.2%
FAMILIES = {
    "sched":   "sched_waking|sched_switch",
    "net":     "net_dev_queue|net_dev_xmit|net_if_receive_skb",
    "syscall": "syscall_entry_|syscall_exit_",
    "block":   "block_rq_issue|block_rq_complete",
    # Lock waits and interrupt time. Both are ALREADY in every run we collected - futex is a
    # syscall so `--syscall --all` caught it, and the profile enables irq_*/softirq_*. Neither
    # has ever been analysed. One family so a single decode serves both.
    "lockirq": ("syscall_entry_futex|syscall_exit_futex|"
                "irq_softirq_entry|irq_softirq_exit|irq_handler_entry|irq_handler_exit"),
}


def shift(hms: str, d: int) -> str:
    """Move a HH:MM:SS wall clock by d seconds.

    Deliberately does NOT wrap past 24 h (finding F8): babeltrace accepts `--end 24:00:21` and
    reads it as the next day, but REJECTS `00:00:21` with a trimmer error. Callers and the
    extractor must agree exactly, or cache keys will not match.
    """
    h, m, s = (int(x) for x in hms.split(":"))
    v = max(0, h * 3600 + m * 60 + s + d)
    return f"{v // 3600:02d}:{(v % 3600) // 60:02d}:{v % 60:02d}"


def windows(t0: str, baseline_s: int = 55, incident_s: int = 60) -> dict:
    """The two windows every script uses, named the same way."""
    return {"baseline": (shift(t0, -baseline_s), t0),
            "incident": (t0, shift(t0, incident_s))}


def cache_path(family: str, begin: str, end: str, cache_dir: str | None = None) -> str | None:
    d = cache_dir or os.environ.get("CTF_CACHE_DIR")
    if not d:
        return None
    tag = f"{begin.replace(':', '')}_{end.replace(':', '')}"
    # "/" not os.path.join: these paths always name cluster files and are pasted into a shell
    # command by ctf_extract, where a Windows backslash would silently break the pipeline.
    return f"{d.rstrip('/')}/{family}_{tag}.zst"


def open_lines(ctf, begin, end, pattern, family=None, regex=None, cache_dir=None):
    """Return (line_iterator, handles) for one window, filtered to `pattern`.

    `regex` mirrors grep -E; inferred from the pattern when not given. `family` enables the
    shared cache - without it, or on a miss, this is exactly the old spawn-babeltrace path.

    The non-context form exists so the existing scripts can swap ONE construction block and
    leave their parsing loop untouched. Re-indenting a 30-line loop is precisely the kind of
    edit that changes behaviour without anyone noticing, and these numbers are already
    measured and written into blueprints.
    """
    if regex is None:
        regex = any(c in pattern for c in "|()[]")
    grep = ["grep", "-E", pattern] if regex else ["grep", pattern]

    path = cache_path(family, begin, end, cache_dir) if family else None
    if path and os.path.exists(path):
        # cache hit: no decoding at all, just decompress and filter
        src = subprocess.Popen(["zstdcat", path], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL)
    else:
        src = subprocess.Popen([BT2, ctf, "--begin", begin, "--end", end],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               env={**os.environ, "TZ": "UTC"})
    flt = subprocess.Popen(grep, stdin=src.stdout, stdout=subprocess.PIPE,
                           text=True, errors="replace")
    src.stdout.close()
    return flt.stdout, [flt, src]


def close_lines(handles):
    """Close and reap what open_lines started. Mirrors the scripts' original teardown."""
    for p in handles or []:
        try:
            if p.stdout and not p.stdout.closed:
                p.stdout.close()
        except Exception:                                              # noqa: BLE001
            pass
        try:
            p.terminate()
        except Exception:                                              # noqa: BLE001
            pass


@contextlib.contextmanager
def stream(ctf, begin, end, pattern, family=None, regex=None, cache_dir=None):
    """Context-manager form of open_lines, for scripts written against it."""
    src, handles = open_lines(ctf, begin, end, pattern, family, regex, cache_dir)
    try:
        yield src
    finally:
        close_lines(handles)


def used_cache(family, begin, end, cache_dir=None) -> bool:
    """For provenance: did this run read the cache or decode? Belongs in the output JSON."""
    p = cache_path(family, begin, end, cache_dir) if family else None
    return bool(p and os.path.exists(p))
