"""
idx_dump.py - print EVERY field of one LTTng index file (.idx) as a table.

Usage:
    python3 idx_dump.py <trace_dir> <channel_name> [rows] [--raw]

Examples:
    python3 idx_dump.py ~/run_A/kernel/kernel channel0_0 8        # first 8 and last 8 rows
    python3 idx_dump.py ~/run_A/kernel/kernel channel0_0 1000     # all rows (if fewer than 2000)
    python3 idx_dump.py ~/run_A/kernel/kernel channel0_0 1000 --raw   # raw integers, no conversion

    <trace_dir>     the folder with channel0_*, metadata and index/
    <channel_name>  channel0_0 (the data file name, without .idx)
    [rows]          how many rows to show at the start and at the end (default 5)
    --raw           print the numbers exactly as stored in the file

Fields in each row (index version 1.1, nine 8-byte numbers, big-endian):
    offset              byte position of the packet in the data file
    packet_size         size of the packet. The file stores BITS. Shown here in bytes
    content_size        part of the packet that holds events. The file stores BITS. Shown in bytes
    timestamp_begin     time of the first event, in trace clock units (ns)
    timestamp_end       time of the last event
    events_discarded    events lost. As far as I know this is a running total up to the end
                        of this packet, not a per-packet count. Not verified here, because
                        the worked trace has 0 everywhere
    stream_id           ID of the stream (channel type)
    stream_instance_id  ID of this stream instance (one per CPU buffer)
    packet_seq_num      packet counter inside the stream

Older files (version 1.0) have 7 fields. If a newer version adds fields, they are
printed as extra0, extra1, ...

The readable mode converts times to UTC with the clock offset from the metadata file.
idx_slice.py must be in the same folder (this script reuses its clock reader).
"""
import os
import struct
import sys
from datetime import datetime, timezone

from idx_slice import clock_from_metadata

MAGIC = 0xC1F1DCC1
NAMES = ["offset", "packet_size", "content_size", "timestamp_begin", "timestamp_end",
         "events_discarded", "stream_id", "stream_instance_id", "packet_seq_num"]


def read_all(path):
    """Return (header, names, rows). Every row holds all fields as plain integers."""
    with open(path, "rb") as f:
        magic, major, minor, entry_len = struct.unpack(">IIII", f.read(16))
        if magic != MAGIC:
            raise SystemExit(f"{path}: bad magic {magic:#x}")
        n = entry_len // 8
        names = NAMES[:n] + [f"extra{i}" for i in range(len(NAMES), n)]
        rows = []
        while True:
            raw = f.read(entry_len)
            if len(raw) < entry_len:
                break
            rows.append(struct.unpack(">" + "Q" * n, raw[:n * 8]))
    return (magic, major, minor, entry_len), names, rows


def utc(ns):
    return datetime.fromtimestamp(ns / 1e9, timezone.utc).strftime("%H:%M:%S.%f")[:-3]


def main():
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        raise SystemExit(__doc__)
    raw_mode = "--raw" in flags
    trace, chan = args[0], args[1]
    rows_to_show = int(args[2]) if len(args) > 2 else 5

    idx_path = os.path.join(trace, "index", chan + ".idx")
    (magic, major, minor, entry_len), names, rows = read_all(idx_path)
    data_size = os.path.getsize(os.path.join(trace, chan))
    n = len(rows)

    print(f"file      : {idx_path}")
    print(f"header    : magic {magic:#010x}, version {major}.{minor}, entry size {entry_len} bytes")
    print(f"fields    : {', '.join(names)}")
    print(f"entries   : {n} packets   data file: {data_size:,} bytes")
    print()

    if raw_mode:
        print(f"{'#':>4} " + " ".join(f"{h[:20]:>20}" for h in names))

        def line(i, r):
            print(f"{i:>4} " + " ".join(f"{v:>20}" for v in r))
    else:
        clock = clock_from_metadata(os.path.join(trace, "metadata"))
        if not clock:
            raise SystemExit("could not read the clock offset from metadata; try --raw")
        freq, offset = clock
        extra = names[9:]
        head = (f"{'#':>4} {'offset':>14} {'packet_size':>12} {'content_size':>13} {'empty':>6} "
                f"{'start (UTC)':>13} {'end (UTC)':>13} {'covers':>8} {'discarded':>10} "
                f"{'stream_id':>9} {'stream_inst':>11} {'seq_num':>8}")
        if extra:
            head += " " + " ".join(f"{e:>8}" for e in extra)
        print(head)
        print("      sizes are in bytes. 'empty' = packet_size - content_size")

        def line(i, r):
            d = dict(zip(names, r))
            psize = d["packet_size"] // 8
            csize = d["content_size"] // 8
            wb = d["timestamp_begin"] * 10**9 // freq + offset
            we = d["timestamp_end"] * 10**9 // freq + offset
            text = (f"{i:>4} {d['offset']:>14,} {psize:>12,} {csize:>13,} {psize - csize:>6,} "
                    f"{utc(wb):>13} {utc(we):>13} {(we - wb) / 1e9:>7.2f}s {d['events_discarded']:>10} "
                    f"{d.get('stream_id', ''):>9} {d.get('stream_instance_id', ''):>11} {d.get('packet_seq_num', ''):>8}")
            if extra:
                text += " " + " ".join(f"{d[e]:>8}" for e in extra)
            print(text)

    for i in range(min(rows_to_show, n)):
        line(i, rows[i])
    if n > 2 * rows_to_show:
        print(f"{'...':>4}")
    for i in range(max(rows_to_show, n - rows_to_show), n):
        line(i, rows[i])

    if n and "events_discarded" in names:
        d = names.index("events_discarded")
        print()
        print(f"events_discarded in the last row: {rows[-1][d]}")


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        # the reader (head, less) closed the pipe early: exit without a traceback
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
