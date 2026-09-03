#!/usr/bin/env python3
"""Add endpoint latency and packet-loss evidence to a run's pack, in place.

The datastore rule now needs two things the older packs do not carry: whether the path is
losing packets (finding F15) and whether anything is actually answering slowly (F13). Packs
already hold runqueue, syscall blocking and on-CPU attribution, so re-decoding a 20 GB trace
for those would be wasted; this adds only what is missing.

Idempotent. Reuses a measurement already made by the endpoint or netloss sweeps if one exists.

    python3 add_netevidence_to_pack.py --run-id <id> --app <app> --pack-dir <dir>
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time

REPO = "/scratch/yuvraj17/stratatrace/repo"
L0ROOT = "/scratch/yuvraj17/stratatrace/data/l0"
EP = f"{REPO}/blueprints/lib/endpoint_latency.py"
NL = f"{REPO}/blueprints/problems/network-path-degradation/scripts/net_loss_signature.py"
SYNTH = f"{REPO}/blueprints/lib/synthesize_gt.py"


def measure(script, ctf, gt, cache, force):
    """Run one measurement, or reuse the cached result of a previous sweep."""
    if os.path.exists(cache) and not force:
        try:
            return json.load(open(cache, encoding="utf-8")), 0.0, True
        except json.JSONDecodeError:
            pass
    t0 = time.time()
    os.makedirs(os.path.dirname(cache) or ".", exist_ok=True)
    r = subprocess.run([sys.executable, script, "--ctf", ctf, "--gt", gt, "--out", cache],
                       capture_output=True, text=True)
    if r.returncode:
        return None, round(time.time() - t0, 1), False
    try:
        return json.load(open(cache, encoding="utf-8")), round(time.time() - t0, 1), False
    except (OSError, json.JSONDecodeError):
        return None, round(time.time() - t0, 1), False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--app", default="sockshop")
    ap.add_argument("--pack-dir", required=True)
    ap.add_argument("--endpoint-cache", default="/scratch/yuvraj17/stratatrace/results/endpoints")
    ap.add_argument("--netloss-cache", default="/scratch/yuvraj17/stratatrace/results/netloss")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    pack_path = os.path.join(a.pack_dir, f"{a.run_id}.json")
    if not os.path.exists(pack_path):
        sys.exit(f"no pack for {a.run_id} in {a.pack_dir}")
    pack = json.load(open(pack_path, encoding="utf-8"))
    if pack.get("endpoints") and pack.get("netloss") and not a.force:
        print(f"SKIP {a.run_id} (pack already has network evidence)")
        return 0

    l0 = os.path.join(L0ROOT, a.app, a.run_id)
    ctf, gt = os.path.join(l0, "ctf"), os.path.join(l0, "ground_truth.json")
    if not os.path.isdir(ctf):
        sys.exit(f"L0 not staged for {a.run_id}: {ctf}")
    if not os.path.exists(gt):
        subprocess.run([sys.executable, SYNTH, "--ctf", ctf, "--out", gt],
                       capture_output=True, text=True)

    ep, ep_s, ep_cached = measure(EP, ctf, gt,
                                  os.path.join(a.endpoint_cache, f"{a.run_id}.json"), a.force)
    nl, nl_s, nl_cached = measure(NL, ctf, gt,
                                  os.path.join(a.netloss_cache, f"{a.run_id}.json"), a.force)

    if ep:
        pack["endpoints"] = {
            "what": "per service endpoint, the gap from a request to the next response, "
                    "baseline vs incident. Flows are identified by their address and port "
                    "tuple; process names are not used, because network events are attributed "
                    "to whatever was on-CPU rather than to the socket owner.",
            "signature": ep.get("signature", {}),
            "slowest": (ep.get("comparison") or [])[:6],
        }
        pack.setdefault("timing_s", {})["endpoint_latency_s"] = ep_s
    if nl:
        pack["netloss"] = {
            "what": "per interface, the share of TCP segments repeating a sequence number "
                    "already seen on the same flow, and buffers queued to a device but never "
                    "transmitted. Both windows.",
            "signature": nl.get("signature", {}),
            "worst": (nl.get("comparison") or [])[:6],
        }
        pack.setdefault("timing_s", {})["net_loss_s"] = nl_s
    if pack.get("timing_s"):
        pack["total_analysis_s"] = round(sum(pack["timing_s"].values()), 1)

    json.dump(pack, open(pack_path, "w"), indent=2)
    e = (pack.get("endpoints") or {}).get("signature", {}).get("slowest") or {}
    n = (pack.get("netloss") or {}).get("signature", {})
    print(f"OK   {a.run_id:44s} endpoint {e.get('p95_x')}x  retrans "
          f"{n.get('worst_retrans_pct')}%  "
          f"({'cached' if ep_cached else f'{ep_s}s'}/"
          f"{'cached' if nl_cached else f'{nl_s}s'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
