#!/usr/bin/env python3
"""Look at ONE incident the way the agent does.

Prints, for a single run: the on-disk layout, the ground-truth label (never shown to the
model), and then the ACTUAL output of each agent tool — i.e. the only view of the dataset
the LLM ever gets. Use it to sanity-check what a fault "looks like" before trusting a
diagnosis.

    python3 peek_run.py                              # first slow_db run, sockshop
    python3 peek_run.py --app trainticket --family noisy_neighbor
    python3 peek_run.py --run /path/to/run_dir --raw  # also dump raw file samples
    python3 peek_run.py --list                        # what runs exist
"""
from __future__ import annotations
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from stratatrace import load_run                      # noqa: E402
from runs import iter_runs, DEFAULT_ROOT              # noqa: E402
from tools import RunTools                            # noqa: E402


def rule(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


def show(obj, cap=2500):
    s = obj if isinstance(obj, str) else json.dumps(obj, indent=2, default=str)
    print(s[:cap] + (f"\n… [{len(s) - cap} more chars]" if len(s) > cap else ""))


def raw_samples(run_dir):
    """A few bytes from each modality's raw file — the pre-tool view."""
    rule("RAW FILES ON DISK")
    for name in sorted(os.listdir(run_dir)):
        p = os.path.join(run_dir, name)
        if os.path.isdir(p):
            files = os.listdir(p)
            tot = sum(os.path.getsize(os.path.join(p, f)) for f in files if os.path.isfile(os.path.join(p, f)))
            print(f"  {name+'/':22s} {len(files):5d} files  {tot/1e6:9.1f} MB")
        else:
            print(f"  {name:22s} {'':5s}        {os.path.getsize(p)/1e6:9.1f} MB")

    run = load_run(run_dir)
    for label, fn in (("TRACES (spans)", run.spans), ("METRICS (long form)", run.metrics),
                      ("KERNEL L1 (per service/second)", run.kernel_l1), ("LOGS", run.logs)):
        rule(f"RAW · {label}")
        try:
            df = fn()
            if hasattr(df, "empty"):
                print(f"shape={df.shape}\ncolumns={list(df.columns)[:14]}\n")
                print(df.head(3).to_string()[:1600] if not df.empty else "(empty)")
            else:
                show(df[:2])
        except Exception as e:                                  # noqa: BLE001
            print(f"(unavailable: {type(e).__name__}: {e})")

    for lvl, fname in (("L2 (wait attribution)", "kernel_l2.jsonl"), ("L3 (English digest)", "kernel_l3.jsonl")):
        p = os.path.join(run_dir, fname)
        rule(f"RAW · KERNEL {lvl}")
        if not os.path.exists(p):
            print("(not derived for this run)")
            continue
        with open(p) as fh:
            for i, line in enumerate(fh):
                if i >= 2:
                    break
                show(json.loads(line), cap=1200)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--app", default="sockshop")
    ap.add_argument("--family", default="slow_db", help="fault family (dir name), e.g. noisy_neighbor")
    ap.add_argument("--run", default=None, help="explicit run dir (overrides app/family)")
    ap.add_argument("--service", default=None, help="focus the tools on one service")
    ap.add_argument("--raw", action="store_true", help="also dump raw per-modality samples")
    ap.add_argument("--list", action="store_true", help="list available runs and exit")
    a = ap.parse_args()

    if a.list:
        for app in ("sockshop", "trainticket"):
            print(f"\n### {app}")
            for r in iter_runs(app, a.root):
                print(f"  {r.fault_family:20s} {r.run_id:45s} target={r.target_service or '(host)':16s} {r.verification}")
        return

    if a.run:
        run_dir, rec = a.run, None
    else:
        rec = next((r for r in iter_runs(a.app, a.root) if r.fault_family == a.family), None)
        if not rec:
            sys.exit(f"no run for family={a.family} in app={a.app}")
        run_dir = rec.dir

    print(f"RUN DIR : {run_dir}")
    if rec:
        print(f"APP     : {rec.app}   FAMILY: {rec.fault_family}   VERIFIED: {rec.verification}")

    rule("GROUND TRUTH  (labels — the model NEVER sees this)")
    show(load_run(run_dir).ground_truth)

    if a.raw:
        raw_samples(run_dir)

    # ---- what the agent actually gets -------------------------------------------------
    run = load_run(run_dir)
    t = RunTools(run, app=(rec.app if rec else a.app))
    svc = a.service
    for label, call in (
        ("list_services()", lambda: t.services()),
        (f"query_metrics({svc or 'all'})", lambda: t.metrics(svc)),
        ("query_host_metrics()", lambda: t.host_metrics()),
        (f"query_traces({svc or 'all'})", lambda: t.traces(svc)),
        (f"query_topology({svc or 'all'})", lambda: t.topology(svc)),
        (f"query_logs({svc or 'all'})", lambda: t.logs(svc)),
        (f"query_kernel({svc or 'all'})", lambda: t.kernel(svc)),
    ):
        rule(f"AGENT TOOL · {label}")
        try:
            out = call()
            if isinstance(out, tuple):                  # (payload, n_rows_scanned)
                out, n = out
                print(f"[scanned {n} rows]")
            show(out)
        except Exception as e:                          # noqa: BLE001
            print(f"(tool error: {type(e).__name__}: {e})")


if __name__ == "__main__":
    main()
