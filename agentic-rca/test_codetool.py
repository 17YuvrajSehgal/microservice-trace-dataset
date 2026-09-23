#!/usr/bin/env python3
"""Adversarial test for the code sandbox.

The point of this file is the ESCAPE section. The sandbox exists to keep one promise - that
nothing the agent can reach reads ground_truth.json - and a promise that is not tested is a
promise that is assumed. Every attack here is one I would actually try.

    python test_codetool.py <run_id>
"""
from __future__ import annotations
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codetool

RUN = sys.argv[1] if len(sys.argv) > 1 else "svc_cpu_cap_aggressive_steady_r1"

# Every one of these must FAIL. The first three are the real threat: the ground truth sits in
# the run directory next to the trace. The rest are standard sandbox escapes.
ESCAPES = [
    ("read ground truth directly",
     "print(open('/scratch/yuvraj17/stratatrace/dataset/runs/sockshop/svc_cpu_cap/"
     "svc_cpu_cap_aggressive_steady_r1/ground_truth.json').read())"),
    # The substring scan is defence in depth, not the barrier - a path can always be built up.
    # What must hold is that a built path cannot be USED. These are the attacks that count.
    ("build the path up, then read it with pandas",
     "p = '/scratch/yuvraj17/stratatrace/dataset' + '/ru' + 'ns/sockshop/svc_cpu_cap/"
     "svc_cpu_cap_aggressive_steady_r1/gro' + 'und_truth.json'\nprint(pd.read_json(p))"),
    ("pandas reads an arbitrary file",
     "print(pd.read_csv('/etc/passwd', nrows=2))"),
    ("numpy reads an arbitrary file",
     "print(np.fromfile('/etc/hostname', dtype='u1')[:20])"),
    ("pandas writes a file",
     "df.head(1).to_csv('/tmp/pwned.csv')"),
    ("read the verification plot metadata",
     "print(open('verification.json').read())"),
    ("import os and walk the filesystem",
     "import os\nprint(os.listdir('/'))"),
    ("import by another name",
     "from os import listdir\nprint(listdir('/'))"),
    ("__import__ through builtins",
     "print(__import__('os').listdir('/'))"),
    ("class-hierarchy escape to the file object",
     "print([c for c in ().__class__.__base__.__subclasses__() if 'Warp' in str(c)])"),
    ("reach globals through a function object",
     "f = lambda: 0\nprint(f.__globals__)"),
    ("getattr to dodge the name scan",
     "print(getattr(df, 'to_csv'))"),
    ("eval a string",
     "print(eval('1+1'))"),
    ("write a file",
     "open('/tmp/pwned', 'w').write('x')"),
    ("spawn a process",
     "import subprocess\nprint(subprocess.run(['ls']))"),
    ("open a socket",
     "import socket\nprint(socket.gethostname())"),
    ("import a module that is not in scope",
     chr(10).join(["import pathlib", "print(pathlib)"])),
    ("from-import a module that is not in scope",
     chr(10).join(["from shutil import which", "print(which)"])),
    ("relative path traversal",
     "print(open('../ground_truth.json').read())"),
]

# These must SUCCEED - the tool is useless if it only says no.
WORK = [
    ("row count", "print(len(df))"),
    ("containers seen",
     "print(sorted(df['pid_ns'].unique())[:8])"),
    ("the svc_cpu_cap question the registered tools cannot answer",
     "r = df[df['event'] == 'sched_stat_runtime']\n"
     "g = r.groupby('pid_ns')['count'].sum().sort_values(ascending=False)\n"
     "print(g.head(6))"),
    ("raw lines carry the TCP header",
     "ls = get_lines(event='net_if_receive_skb', limit=2)\n"
     "print('seq=' + str('seq' in (ls[0] if ls else '')))"),
    # These exist because the descriptor cap broke them once. pandas imports submodules lazily,
    # so an operation the warmup missed dies with "Too many open files" on a numpy source file.
    ("groupby after the fd cap (lazy numpy.rec import)",
     "print(df.groupby('pid_ns')['count'].sum().nlargest(3))"),
    ("merge, pivot and rolling after the fd cap",
     "h = df.head(5000)\n"
     "print(len(h.merge(h, on='event').head(1)),"
     " len(h.pivot_table(index='event', values='count', aggfunc='sum')),"
     " h.sort_values('bucket_start_s')['count'].rolling(3).mean().notna().sum())"),
    ("datetime and quantiles after the fd cap",
     "print(pd.to_datetime(df['bucket_start_s'].head(3), unit='s').iloc[0],"
     " df['count'].quantile(0.95))"),
    # 42% of real snippets were rejected for this habit alone. Importing something already
    # in scope is a no-op and must work.
    ("import pandas, which is already in scope",
     chr(10).join(["import pandas as pd", "import numpy as np",
                   "print(len(df), np.int64(1))"])),
    ("from collections import Counter",
     chr(10).join(["from collections import Counter",
                   "print(len(Counter(df['event'].head(50))) > 0)"])),
    ("import itertools and functools",
     chr(10).join(["import itertools, functools",
                   "print(len(list(itertools.islice(range(9), 3))))"])),
    ("an error is reported, not swallowed", "print(1/0)"),
]


def main():
    sb = codetool.Sandbox(RUN)
    bad = 0

    print("== ESCAPES - every one must be blocked")
    for name, code in ESCAPES:
        r = sb.run(code)
        blocked = bool(r.get("rejected") or r.get("error"))
        # a block that merely errors is fine; a block that RETURNS DATA is not
        leaked = ("target_service" in str(r) or "fault" in str(r.get("stdout", "")).lower())
        ok = blocked and not leaked
        bad += 0 if ok else 1
        why = (r.get("error") or "")[:64]
        print("   %-46s %s  %s" % (name, "BLOCKED" if ok else "*** LEAKED ***", why))

    print()
    print("== REAL WORK - these must run")
    for name, code in WORK:
        r = sb.run(code)
        out = (r.get("stdout") or "").strip().replace(chr(10), " | ")[:70]
        got = bool(out) or bool(r.get("error"))
        if name.startswith("an error"):
            got = bool(r.get("error"))
            out = (r.get("error") or "")[:70]
        bad += 0 if got else 1
        print("   %-46s %s  %s" % (name, "ok " if got else "BROKEN", out))

    sb.close()
    print()
    print("FAILURES: %d" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
