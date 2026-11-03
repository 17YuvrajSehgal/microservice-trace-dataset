#!/usr/bin/env python3
"""
pidmap.py - which thread belongs to which process, read from the trace's own statedump.

Usage:
    python3 pidmap.py <trace_dir> [--out FILE]

Why:
    On a switch/router trace the events carry no pid, only the tid of the thread that was
    switched in or out. The kernel still told LTTng the whole process table once, at the
    start of the session (lttng_statedump_process_state). This script pulls that table out
    and writes it as a TSV that the other tools accept with --pidmap, so "threads of the
    same process" becomes answerable (spawnerThr and commsTx are both pid 7087, say).

How:
    Runs `babeltrace2 --clock-gmt <trace_dir>` ($BT2 if set), keeps the statedump lines, and
    stops the decoder as soon as `lttng_statedump_end` passes - the dump sits at the start of
    the trace, so this never reads the whole thing.

Output:
    <trace_dir basename>.pidmap.tsv in the current folder (or --out FILE), one line per
    thread: tid, pid, ppid, name, type (0 = user thread, 1 = kernel thread). A summary line
    says how many threads and processes were mapped. If the trace has no statedump the file
    is empty and the summary says so; the tools then fall back to one thread = one row.
"""
import os
import subprocess
import sys

from tracelib import parse


def parse_dump(lines):
    """Statedump lines -> {tid: (pid, ppid, name, type)}. Stops at lttng_statedump_end."""
    out = {}
    for line in lines:
        if ' lttng_statedump_end:' in line:
            break
        if ' lttng_statedump_process_state:' not in line:
            continue
        ev = parse(line)
        if ev is None:
            continue
        f = ev.fields
        if 'tid' in f:
            out[f['tid']] = (f.get('pid', f['tid']), f.get('ppid', 0), f.get('name', '?'),
                             f.get('type', 0))
    return out


def write_map(m, out):
    with open(out, 'w') as w:
        w.write('# tid\tpid\tppid\tname\ttype\n')
        for tid in sorted(m):
            pid, ppid, name, typ = m[tid]
            w.write(f"{tid}\t{pid}\t{ppid}\t{name}\t{typ}\n")


def main():
    if '--selftest' in sys.argv:
        return _selftest()
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        raise SystemExit(__doc__)
    trace = args[0].rstrip('/\\')
    out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv \
        else os.path.basename(trace) + '.pidmap.tsv'
    bt = os.environ.get('BT2', 'babeltrace2')
    proc = subprocess.Popen([bt, '--clock-gmt', trace], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, errors='replace')
    m = parse_dump(proc.stdout)          # returns at statedump_end: stop decoding there
    proc.stdout.close()
    proc.terminate()
    proc.wait()
    write_map(m, out)
    pids = {v[0] for v in m.values()}
    if m:
        print(f"{len(m)} threads in {len(pids)} processes -> {out}")
    else:
        print(f"no lttng_statedump_process_state events found (statedump not enabled?) -> {out} is empty")


def _selftest():
    lines = [
        '[21:12:27.300000000] (+0.000000100) 1-A-5 lttng_statedump_start: { cpu_id = 0 }, { }',
        '[21:12:27.300000100] (+0.000000100) 1-A-5 lttng_statedump_process_state: { cpu_id = 0 }, '
        '{ tid = 7231, vtid = 7231, pid = 7087, vpid = 7087, ppid = 7010, vppid = 7010, '
        'name = "spawnerThr", type = 0, mode = 5, submode = 0, status = 5, ns_level = 0, cpu = 2 }',
        '[21:12:27.300000200] (+0.000000100) 1-A-5 lttng_statedump_process_state: { cpu_id = 0 }, '
        '{ tid = 7249, vtid = 7249, pid = 7087, vpid = 7087, ppid = 7010, vppid = 7010, '
        'name = "commsTx", type = 0, mode = 5, submode = 0, status = 5, ns_level = 0, cpu = 2 }',
        '[21:12:27.300000300] (+0.000000100) 1-A-5 lttng_statedump_process_state: { cpu_id = 0 }, '
        '{ tid = 3, vtid = 3, pid = 3, vpid = 3, ppid = 2, vppid = 2, name = "ksoftirqd/0", '
        'type = 1, mode = 5, submode = 0, status = 5, ns_level = 0, cpu = 0 }',
        '[21:12:27.400000000] (+0.000000100) 1-A-5 lttng_statedump_end: { cpu_id = 0 }, { }',
        '[21:12:27.500000000] (+0.000000100) 1-A-5 lttng_statedump_process_state: { cpu_id = 0 }, '
        '{ tid = 9999, pid = 9999, ppid = 1, name = "after_end", type = 0 }',
    ]
    m = parse_dump(lines)
    assert m == {7231: (7087, 7010, 'spawnerThr', 0), 7249: (7087, 7010, 'commsTx', 0),
                 3: (3, 2, 'ksoftirqd/0', 1)}, m
    import tempfile
    from tracelib import load_pidmap
    with tempfile.NamedTemporaryFile('w', delete=False, suffix='.tsv') as tf:
        p = tf.name
    try:
        write_map(m, p)
        back = load_pidmap(p)
        assert back[7249] == (7087, 7010, 'commsTx') and back[3][2] == 'ksoftirqd/0', back
    finally:
        os.unlink(p)
    print("pidmap selftest OK")


if __name__ == '__main__':
    try:
        main()
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
