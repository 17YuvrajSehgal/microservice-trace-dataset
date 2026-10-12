"""
idx_slice.py - cut a time window out of an LTTng CTF 2 trace by using the
index/*.idx files. It copies only the packets that overlap the window into a
small new trace. Then babeltrace2 reads the small trace in seconds.

Usage:
    python3 idx_slice.py <trace_dir> <start> <end> <out_dir> [--offset-ns N]

    <trace_dir>  the folder that holds channel0_0, ..., metadata and index/
                 (for the worked run: ~/run_A/kernel/kernel)
    <start>,<end> UTC, as "YYYY-MM-DD HH:MM:SS" (fractions allowed)
    <out_dir>    new folder, must not exist yet

Then trim exactly and read:
    babeltrace2 --clock-gmt --begin "<start>" --end "<end>" <out_dir>

The packets are whole 8 MiB blocks, so the small trace holds a bit more than
your window (up to about 2 s extra on each side per CPU). The --begin and
--end flags of babeltrace2 trim the rest.

How the time is converted:
    The idx file stores time as clock cycles of the trace clock. To get UTC,
    the script reads "offset-from-origin" from the clock-class record in the
    metadata file. If it cannot find it, give --offset-ns yourself:
        offset = clock_realtime_ns - clock_monotonic_ns   (from runinfo_start.txt)
    The script prints the offset it used. Check it: the first event that
    babeltrace2 prints should fall inside the first packet's time range.

idx format (big-endian). Header: magic c1f1dcc1, major, minor, entry_len
(4 bytes each). Then one entry per packet: offset, packet_size (bits),
content_size (bits), timestamp_begin, timestamp_end, events_discarded, ...
(8 bytes each).
"""
import calendar
import glob
import json
import os
import re
import shutil
import struct
import sys
from datetime import datetime

MAGIC = 0xC1F1DCC1


def parse_utc_ns(text):
    text = text.strip()
    frac = 0
    if "." in text:
        text, f = text.split(".", 1)
        frac = int(f.ljust(9, "0")[:9])
    dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    return calendar.timegm(dt.timetuple()) * 10**9 + frac


def read_idx(path):
    with open(path, "rb") as f:
        head = f.read(16)
        magic, major, minor, entry_len = struct.unpack(">IIII", head)
        if magic != MAGIC:
            raise SystemExit(f"{path}: bad magic {magic:#x}")
        entries = []
        while True:
            raw = f.read(entry_len)
            if len(raw) < entry_len:
                break
            off, psize, csize, tb, te, disc = struct.unpack(">QQQQQQ", raw[:48])
            entries.append((off, psize // 8, tb, te, disc))
    return entries


def clock_from_metadata(path):
    """Return (frequency, offset_ns) from the clock-class record, or None."""
    with open(path, "rb") as f:
        data = f.read()
    for rec in data.split(b"\x1e"):
        rec = rec.strip()
        if b'"clock-class"' not in rec[:200]:
            continue
        try:
            obj = json.loads(rec.decode("utf-8", "replace"))
        except ValueError:
            continue
        if obj.get("type") != "clock-class":
            continue
        freq = obj.get("frequency", 10**9)
        off = obj.get("offset-from-origin", {})
        ns = off.get("seconds", 0) * 10**9 + off.get("cycles", 0) * 10**9 // freq
        return freq, ns
    return None


def main():
    args = sys.argv[1:]
    manual = None
    if "--offset-ns" in args:
        i = args.index("--offset-ns")
        manual = int(args[i + 1])
        del args[i:i + 2]
    if len(args) != 4:
        raise SystemExit(__doc__)
    trace, start, end, out = args
    t0, t1 = parse_utc_ns(start), parse_utc_ns(end)

    freq, offset = 10**9, None
    meta = os.path.join(trace, "metadata")
    got = clock_from_metadata(meta)
    if manual is not None:
        offset = manual
    elif got:
        freq, offset = got
    else:
        raise SystemExit("could not read the clock offset from metadata; pass --offset-ns")
    print(f"clock frequency {freq} Hz, offset {offset} ns")

    def to_wall(cycles):
        return cycles * 10**9 // freq + offset

    if os.path.exists(out):
        raise SystemExit(f"{out} already exists")
    os.makedirs(out)
    shutil.copy(meta, os.path.join(out, "metadata"))

    total_in = total_out = 0
    for idx_path in sorted(glob.glob(os.path.join(trace, "index", "*.idx"))):
        name = os.path.basename(idx_path)[:-4]
        data_path = os.path.join(trace, name)
        entries = read_idx(idx_path)
        picked = [e for e in entries if to_wall(e[3]) >= t0 and to_wall(e[2]) <= t1]
        with open(data_path, "rb") as src, open(os.path.join(out, name), "wb") as dst:
            for off, size, tb, te, disc in picked:
                src.seek(off)
                dst.write(src.read(size))
                total_out += size
        total_in += sum(e[1] for e in entries)
        if entries:
            print(f"{name}: {len(picked):>3} of {len(entries):>3} packets  "
                  f"(first packet starts {to_wall(entries[0][2])/1e9:.3f}, "
                  f"last ends {to_wall(entries[-1][3])/1e9:.3f} epoch s)")
    print(f"copied {total_out/1e6:.0f} MB of {total_in/1e6:.0f} MB -> {out}")


if __name__ == "__main__":
    main()
