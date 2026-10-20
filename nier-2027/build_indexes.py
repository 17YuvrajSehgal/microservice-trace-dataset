#!/usr/bin/env python3
"""Build CTF count indexes for the ablation runs. Run inside WSL (needs babeltrace2 2.1.2).

The agentic runs keep their CTF at trace/kernel, not the kernel/kernel the cluster
builder assumes, and they need the --with-lines sidecar because the agent's ctf_lines
tool reads it instead of re-decoding.

    wsl -e python3 nier-2027/build_indexes.py --out Blueprint/agent/ctf-index RUN_DIR...
"""
from __future__ import annotations
import argparse, os, sys, time

os.environ.setdefault("BT2", "/usr/bin/babeltrace2")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "blueprints", "lib"))
import build_ctf_index as B  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dirs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--ctf-subdir", default="trace/kernel")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    ok = fail = skip = 0
    t_all = time.time()
    for rd in a.run_dirs:
        rd = rd.rstrip("/")
        name = os.path.basename(rd)
        tsv = os.path.join(a.out, name + ".tsv.gz")
        lines = os.path.join(a.out, name + ".lines.gz")
        if os.path.exists(tsv) and os.path.exists(lines) and not a.force:
            print(f"SKIP  {name}", flush=True); skip += 1; continue
        t = time.time()
        r = B.build(rd, tsv, ctf_subdir=a.ctf_subdir, verbose=False, lines_path=lines)
        if "error" in r:
            print(f"FAIL  {name}: {r['error']}", flush=True); fail += 1; continue
        print(f"OK    {name}  {r['events_decoded']:>9,} ev -> {r['rows']:>7,} rows  "
              f"{r['size_bytes']/1e6:5.1f} MB  {r.get('n_pid_ns',0):>3} ns  {time.time()-t:5.1f}s",
              flush=True)
        ok += 1
    print(f"\n{ok} built, {skip} skipped, {fail} failed in {time.time()-t_all:.0f}s")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
