"""
idx_summary.py - trace-level facts from the index files (index/*.idx) of an
LTTng CTF 2 kernel trace. Nothing is decoded, so it takes seconds.

Usage:
    python3 idx_summary.py <trace_dir> [--rate SECONDS]

Examples:
    python3 idx_summary.py ~/run_A/kernel/kernel
    python3 idx_summary.py ~/run_A/kernel/kernel --rate 10

    <trace_dir>  the folder with channel0_*, metadata and index/
    --rate N     also print how much trace data was written per N seconds,
                 all CPUs together. Each packet's bytes are spread evenly over
                 the time that packet covers.

What it prints:
    date, start, end and length of the trace, number of CPUs and packets,
    packet size, data size, and four health checks:
      lost events  : is events_discarded non-zero in any row?
      time gaps    : does every packet start where the previous one ended?
      seq gaps     : does packet_seq_num go up by exactly 1?
      file sizes   : does the sum of packet sizes equal the data file size?
    and one line per CPU.

Two things to remember when you read the start and end:
    "trace start" is when the first packet was OPENED, not when the first event
    happened. On the worked trace it was 0.91 s earlier than the first event.
    "trace end" is when the last packet was closed. On the worked trace it was
    7 ms after the last event.
    For the exact first event use:  babeltrace2 --clock-gmt <trace_dir> | head -n 1

idx_dump.py and idx_slice.py must be in the same folder as this script.
"""
import glob
import os
import re
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone

from idx_dump import read_all
from idx_slice import clock_from_metadata


def cpu_key(path):
    m = re.search(r"_(\d+)\.idx$", path)
    return int(m.group(1)) if m else 0


def clock(ns, with_date=False):
    fmt = "%Y-%m-%d %H:%M:%S.%f" if with_date else "%H:%M:%S.%f"
    return datetime.fromtimestamp(ns / 1e9, timezone.utc).strftime(fmt)[:-3]


def main():
    args = sys.argv[1:]
    rate = None
    if "--rate" in args:
        i = args.index("--rate")
        rate = float(args[i + 1])
        del args[i:i + 2]
    if len(args) != 1:
        raise SystemExit(__doc__)
    trace = args[0]

    got = clock_from_metadata(os.path.join(trace, "metadata"))
    if not got:
        raise SystemExit("could not read the clock offset from the metadata file")
    freq, offset = got

    def wall(c):
        return c * 10**9 // freq + offset

    files = sorted(glob.glob(os.path.join(trace, "index", "*.idx")), key=cpu_key)
    if not files:
        raise SystemExit(f"no .idx files in {os.path.join(trace, 'index')}")

    cpus = []          # one dict per CPU
    versions = set()
    for path in files:
        header, names, rows = read_all(path)
        versions.add(header[1:4])          # (major, minor, entry_len)
        chan = os.path.basename(path)[:-4]
        col = {n: names.index(n) for n in names}
        pk = []        # (begin_ns, end_ns, packet_bytes, content_bytes)
        for r in rows:
            pk.append((wall(r[col["timestamp_begin"]]), wall(r[col["timestamp_end"]]),
                       r[col["packet_size"]] // 8, r[col["content_size"]] // 8))
        disc = [r[col["events_discarded"]] for r in rows] if "events_discarded" in col else []
        seqs = [r[col["packet_seq_num"]] for r in rows] if "packet_seq_num" in col else []
        data_file = os.path.join(trace, chan)
        cpus.append({
            "chan": chan,
            "pk": pk,
            "disc_rows": sum(1 for d in disc if d != 0),
            "disc_last": disc[-1] if disc else 0,
            # (packet number, previous packet closed, this packet opened)
            "gap_list": [(i + 1, a[1], b[0]) for i, (a, b) in enumerate(zip(pk, pk[1:])) if b[0] != a[1]],
            "seq_gaps": sum(1 for a, b in zip(seqs, seqs[1:]) if b != a + 1) if seqs else None,
            "sum_bytes": sum(p[2] for p in pk),
            "file_bytes": os.path.getsize(data_file) if os.path.exists(data_file) else None,
        })

    allpk = [p for c in cpus for p in c["pk"]]
    if not allpk:
        raise SystemExit("the index files hold no packets")
    start = min(p[0] for p in allpk)
    end = max(p[1] for p in allpk)
    sizes = Counter(p[2] for p in allpk)
    common_size, common_n = sizes.most_common(1)[0]
    total_pk = sum(p[2] for p in allpk)
    total_used = sum(p[3] for p in allpk)
    durs = [(p[1] - p[0]) / 1e9 for p in allpk]
    per_cpu_n = [len(c["pk"]) for c in cpus]

    for c in cpus:
        c["time_gaps"] = len(c["gap_list"])
    all_gaps = [(c["chan"].split("_")[-1], n, prev_end, begin)
                for c in cpus for (n, prev_end, begin) in c["gap_list"]]
    bad_disc = [c for c in cpus if c["disc_rows"]]
    bad_time = [c for c in cpus if c["time_gaps"]]
    bad_seq = [c for c in cpus if c["seq_gaps"]]
    bad_size = [c for c in cpus if c["file_bytes"] is not None and c["file_bytes"] != c["sum_bytes"]]

    print(f"trace         : {trace}")
    major, minor, entry_len = sorted(versions)[0]
    print(f"index         : version {major}.{minor}, {entry_len}-byte rows, "
          f"{len(cpus)} CPUs ({cpus[0]['chan']} ... {cpus[-1]['chan']})")
    print(f"clock         : {freq:,} Hz, offset {offset} ns")
    print(f"date (UTC)    : {clock(start, True)[:10]}")
    print(f"trace start   : {clock(start)}   (earliest packet opened, on any CPU. The first event comes later)")
    print(f"trace end     : {clock(end)}   (latest packet closed)")
    print(f"duration      : {(end - start) / 1e9:.2f} s")
    print(f"packets       : {len(allpk):,} in total ({min(per_cpu_n)} to {max(per_cpu_n)} per CPU)")
    print(f"packet size   : {common_size:,} bytes ({common_size / 2**20:.1f} MiB) in "
          f"{100 * common_n / len(allpk):.1f}% of packets")
    print(f"data          : {total_pk / 1e6:,.0f} MB in packets, {total_used / 1e6:,.0f} MB used")
    print(f"packet time   : median {statistics.median(durs):.2f} s, longest {max(durs):.2f} s")

    def verdict(bad, ok, what):
        if not bad:
            return ok
        return f"WARNING: {what} on CPUs " + ", ".join(c["chan"].split("_")[-1] for c in bad)

    print(f"lost events   : {verdict(bad_disc, 'none (events_discarded is 0 in every row)', 'events_discarded is non-zero')}")
    if not all_gaps:
        print("time gaps     : none (every packet starts when the previous one ended)")
    else:
        sizes_ms = [(b - e) / 1e6 for _, _, e, b in all_gaps]
        print(f"time gaps     : CHECK: {len(all_gaps)} places where a packet does not start when the previous one "
              f"ended (largest {max(sizes_ms, key=abs):.3f} ms). Listed below the CPU table")
    print(f"seq gaps      : {verdict(bad_seq, 'none (packet_seq_num goes up by 1)', 'packet_seq_num skips')}")
    print(f"file sizes    : {verdict(bad_size, 'match the index (packet sizes add up to each data file)', 'data file size differs from the index')}")

    print()
    print(f"{'cpu':>4} {'packets':>8} {'first opened':>13} {'last closed':>12} {'MB':>8} "
          f"{'lost rows':>10} {'time gaps':>10} {'seq gaps':>9}")
    for c in cpus:
        pk = c["pk"]
        if not pk:
            continue
        print(f"{c['chan'].split('_')[-1]:>4} {len(pk):>8} {clock(pk[0][0]):>13} {clock(pk[-1][1]):>12} "
              f"{c['sum_bytes'] / 1e6:>8,.0f} {c['disc_rows']:>10} {c['time_gaps']:>10} "
              f"{'' if c['seq_gaps'] is None else c['seq_gaps']:>9}")

    if all_gaps:
        print()
        print("time gaps: the packet opened later (+) or earlier (-) than the previous one closed")
        print(f"{'cpu':>4} {'packet':>7} {'previous closed':>16} {'this opened':>13} {'gap (ms)':>10}")
        for cpu, n, prev_end, begin in all_gaps[:60]:
            print(f"{cpu:>4} {n:>7} {clock(prev_end):>16} {clock(begin):>13} {(begin - prev_end) / 1e6:>+10.3f}")
        if len(all_gaps) > 60:
            print(f"... and {len(all_gaps) - 60} more")

    if rate:
        width = int(rate * 10**9)
        base = (start // width) * width
        bins = {}
        for p in allpk:
            tb, te, nbytes = p[0], p[1], p[3]
            if te <= tb:
                i = (tb - base) // width
                bins[i] = bins.get(i, 0) + nbytes
                continue
            for i in range((tb - base) // width, (te - base) // width + 1):
                lo = max(tb, base + i * width)
                hi = min(te, base + (i + 1) * width)
                if hi > lo:
                    bins[i] = bins.get(i, 0) + nbytes * (hi - lo) / (te - tb)
        first, last = min(bins), max(bins)
        series = [(i, bins.get(i, 0) / rate / 1e6) for i in range(first, last + 1)]
        top = max(v for _, v in series) or 1
        print()
        print(f"data written per {rate:g} s, all CPUs together (MB per second)")
        print("the first and last rows are only partly covered. A long packet spreads over several rows,")
        print("so a sharp change shows up a few seconds wide.")
        print(f"{'time (UTC)':>11} {'MB/s':>8}")
        for i, v in series:
            print(f"{clock(base + i * width)[:8]:>11} {v:>8.1f}  {'#' * int(50 * v / top)}")


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
