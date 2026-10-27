#!/usr/bin/env python3
"""Collect the evidence needed to JUDGE a combo's runs by hand (see JUDGING.md).

Does NOT grade. Prints, per run: ground truth (fault/target/scope/window from the recipe's
own record) and the agent's committed verdict (fault_type/where/when/what_is_wrong). The call
is made by a human/LLM reading this, not by a keyword rule.

    python gather.py <results_dir>        # e.g. .../results/sockshop/svc_mem_cap
"""
import json, glob, os, sys


def truth(run_dir):
    for p in (os.path.join(run_dir, "ground_truth.json"),
              os.path.join(run_dir, "meta", "ground_truth.json")):
        if os.path.exists(p):
            f = (json.load(open(p)) or {}).get("fault", {})
            return {"name": f.get("name"), "scope": f.get("scope"),
                    "target": f.get("target_service"),
                    "params": f.get("parameters"),
                    "window": [f.get("injection_start_utc"), f.get("injection_end_utc")]}
    return {}


def main():
    rdir = sys.argv[1]
    # map run_id -> run_dir under the data tree (passed as 2nd arg, or guess)
    data = sys.argv[2] if len(sys.argv) > 2 else "/scratch/yuvraj17/stratatrace/data/stratatrace-v2"
    for f in sorted(glob.glob(os.path.join(rdir, "*", "result.json"))):
        r = json.load(open(f))
        rid = r["run_id"]
        cand = glob.glob(os.path.join(data, "*", "*", rid)) or glob.glob(os.path.join(data, "*", rid))
        t = truth(cand[0]) if cand else {}
        v = r.get("verdict", {})
        print("=" * 90)
        print("RUN", rid)
        print("  GT    :", t.get("name"), "| scope", t.get("scope"), "| target", t.get("target"),
              "| params", t.get("params"), "| window", t.get("window"))
        print("  AGENT :", repr(v.get("fault")), "| where", repr(str(v.get("where"))[:70]),
              "| when", v.get("when"))
        print("  WHAT  :", str(v.get("what_is_wrong"))[:400])


if __name__ == "__main__":
    main()
