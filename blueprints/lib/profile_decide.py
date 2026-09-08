#!/usr/bin/env python3
"""Decide from a signal PROFILE instead of hardcoded cuts.

THE PROBLEM THIS ADDRESSES
--------------------------
Every threshold in blueprint_decide.py is a constant that describes our deployments rather than
the fault. Measured on v2:

  * CONTENDED = 0.55 INVERTED between applications - Train Ticket's co-tenant runs sit at
    0.213-0.282 and its healthy runs at 0.657-0.710.
  * softirq_x for svc_mem_cap inverted in DIRECTION - 0.71-0.80 on Sock Shop, 1.55-7.42 on
    Train Ticket, against a healthy range near 1.0.
  * DISK_IOPS_GAINED = 2000 scored 1/10, because Train Ticket's own tracing caps how large the
    disk fault can be.
  * Host utilisation drifted 4.6x DURING collection, so an absolute level partly measures when
    a run happened.

The library scored 71% on the application its thresholds came from and 29% on the other.

WHAT REPLACES THEM
------------------
Not "hand the number to the agent and let it decide" - "is 600 high?" is unanswerable without a
reference, and a blueprint that omits the reference has not removed the threshold, it has moved
it into the model's prior where it is invisible and changes with the model version.

Instead, two things the blueprint can carry without naming a system:

  1. A REFERENCE. Every signal here is already incident / this-run's-own-baseline, so it is
     deployment-normalised before we start. What remains is "how large a ratio is unusual", and
     that comes from the healthy runs' own spread, per deployment, via median and MAD. Measured:
     healthy ratios cluster tightly at 1.0 on BOTH applications (hardirq_x 0.91-1.04 and
     0.93-1.12; total_iops_x 0.98-1.04 and 0.98-1.01), which is why a sigma score transfers
     where a level does not.

  2. A DIRECTION per signal, and which look-alike moves it the other way. That is mechanism,
     not calibration, so it is a property of the fault.

A useful consequence: a signal that is noisy on healthy runs gets a large MAD and is
automatically down-weighted, with nothing hand-tuned. `worst_endpoint_x` reaches 1485x on
healthy Train Ticket runs, so a 4836x reading is only a few sigma; `n_slowed_2x` is tight on
healthy runs, so it carries more weight. The reference picks the robust signal for us.

HONEST LIMIT
------------
This does not eliminate constants. It collapses twelve deployment-specific numbers into two
dimensionless ones - how many sigma counts as anomalous, and how much of a signature must match
- shared by every signal and both applications. That is a large reduction in fragility, not zero.

    python3 profile_decide.py --packs <dir> --tasks <file> [--agent-view <run_id>] [--out json]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blueprint_decide as BD                                          # noqa: E402

# ---- the two dimensionless constants, and there are only two -------------------------------
Z_ANOMALOUS = 3.0      # sigma at which a signal counts as moved. One number, every signal.
MATCH_MIN = 0.60       # fraction of a signature's signals that must be moved the right way.

# MAD of zero happens when healthy runs agree exactly. Floor it relative to the median so the
# score stays finite without inventing a scale.
MAD_FLOOR_FRAC = 0.02


def _sig(pack, section, key):
    return ((pack.get(section) or {}).get("signature") or {}).get(key)


# ---- the signals. Every one is a RATIO (incident / this run's own baseline) or a count, so it
# ---- is already normalised for the deployment before the reference is applied.
def _rq_max(p):
    rows = (p.get("runqueue_delay") or {}).get("top_by_inflation") or []
    xs = [r.get("p95_x") for r in rows if isinstance(r.get("p95_x"), (int, float))]
    return max(xs) if xs else None


def _socket_x(p):
    rows = (p.get("blocking_syscall") or {}).get("top_by_inflation") or []
    hits = [r["p95_x"] for r in rows
            if r.get("p95_x")
            and r["comm_syscall"].split("|")[-1] in BD.SOCKET_CALLS
            and not BD.is_infra(r["comm_syscall"].split("|")[0])]
    return max(hits) if hits else None


def _util_ratio(p):
    b, i = _sig(p, "oncpu", "host_util_baseline"), _sig(p, "oncpu", "host_util_incident")
    return round(i / b, 4) if (b and i is not None) else None


def _iops_per_irq(p):
    g, x = _sig(p, "blockio", "io_newcomer_iops_gained"), _sig(p, "irq", "hardirq_x")
    return round(g / x, 1) if (g is not None and x) else None


def _endpoint_x(p):
    s = (_sig(p, "endpoints", "slowest") or {})
    return s.get("p95_x")


SIGNALS = {
    "util_ratio": _util_ratio,
    "util_incident": lambda p: _sig(p, "oncpu", "host_util_incident"),
    "thief_cores": lambda p: _sig(p, "oncpu", "thief_cores_gained"),
    "loser_cores": lambda p: _sig(p, "oncpu", "biggest_loser_cores"),
    "rq_max": _rq_max,
    "socket_block_x": _socket_x,
    "endpoint_x": _endpoint_x,
    "n_slowed_2x": lambda p: _sig(p, "endpoints", "n_slowed_2x"),
    "retrans_pct": lambda p: _sig(p, "netloss", "worst_retrans_pct"),
    "iops_gained": lambda p: _sig(p, "blockio", "io_newcomer_iops_gained"),
    "iops_per_irq": _iops_per_irq,
    "total_iops_x": lambda p: _sig(p, "blockio", "total_iops_x"),
    "hardirq_x": lambda p: _sig(p, "irq", "hardirq_x"),
    "queue_depth_x": lambda p: _sig(p, "blockio", "queue_depth_x"),
}

# ---- what each blueprint EXPECTS, as directions. Mechanism, not calibration. --------------
#
# "up"/"down" is the direction the fault moves the signal away from healthy. Nothing here is a
# magnitude, so nothing here is deployment-specific. Every direction below is either the
# documented mechanism or measured on v2 across both applications.
# A signature has three kinds of clause, and only the first can EARN score:
#
#   "up" / "down"        positive evidence, relative to HEALTHY. Contributes to the score.
#   "flat"               a VETO. Must hold, contributes nothing.
#   ("gt", other)        this signal is more anomalous than `other`. Contributes to the score.
#
# The first version of this file got two things wrong, and both are worth keeping written down.
#
# 1. FLAT COUNTED AS EVIDENCE. A signature of three "flat" clauses and one "up" would score 0.75
#    on any run where nothing much happened, so `datastore-wait` fired on 14 of 20 healthy runs
#    and 62% of its fires were false. Absence of a contradicting signal is not evidence FOR a
#    diagnosis. Vetoes now gate the verdict without contributing to it.
#
# 2. DIRECTIONS WERE WRITTEN RELATIVE TO A LOOK-ALIKE, NOT TO HEALTHY. `iops_per_irq` was marked
#    "down" for the memory cap because it is lower than the DISK fault. Against healthy it is
#    UP - healthy sits near 40-66, the memory cap at 62-352, the disk at 546-719. Both faults
#    move it the same way. So service-memory-cap scored 0/16: the one signal it was counting on
#    was pointing the wrong way by construction.
#
#    That exposes a real limit of direction-only signatures: they cannot say "up, but less up
#    than the other fault". Hence ("gt", other) - a comparison between two sigma scores, which
#    is dimensionless and needs no constant. It is the same discriminator that DISK_IOPS_PER_IRQ
#    = 450 expressed as a magnitude, without the magnitude.
SIGNATURES = {
    "host-cpu-saturation": {
        "util_incident": "up",       # a bounded quantity: it runs into its ceiling
        "thief_cores": "up",         # something took the CPU
        "util_ratio": "up",
        ("gt", "hardirq_x"): "thief_cores",   # CPU was taken, not reclaimed
    },
    "cpu-contention-co-tenant": {
        "thief_cores": "up",         # a newcomer appears...
        "util_ratio": "up",          # ...and the host gets busier
        "hardirq_x": "flat",         # VETO: the memory cap's stress tool also eats a core
                                     # (LATENCY-CAUSES: "memory stress -> CPU")
        "util_incident": "flat",     # VETO: not saturated, or it is host saturation
    },
    "service-cpu-throttle": {
        "util_ratio": "down",        # the quota makes the system do LESS
        "loser_cores": "down",       # someone loses CPU
        "rq_max": "up",              # while threads wait longer - working less, waiting more
        "thief_cores": "flat",       # VETO: nobody took it
    },
    "host-disk-saturation": {
        "iops_gained": "up",         # requests arrive
        "total_iops_x": "up",
        ("gt", "hardirq_x"): "iops_per_irq",  # a FLOOD: arrivals outrun the interrupt rise
    },
    "service-memory-cap": {
        "hardirq_x": "up",           # reclaim drives device interrupts
        ("gt", "iops_per_irq"): "hardirq_x",  # RECLAIM: the interrupt rise outruns arrivals.
                                     # This is the disk/memcap discriminator with no magnitude.
    },
    "network-path-degradation": {
        "retrans_pct": "up",         # the path is losing packets
        "n_slowed_2x": "up",         # and endpoints answer slower
    },
    "datastore-wait": {
        "n_slowed_2x": "up",         # endpoints answer slower
        "retrans_pct": "flat",       # VETO: not packet loss (F15)
        "rq_max": "flat",            # VETO: not CPU starvation
        "thief_cores": "flat",       # VETO: nobody took the CPU
    },
}

OWNS = {
    "host-cpu-saturation": {"anomaly_cpu"},
    "service-cpu-throttle": {"svc_cpu_cap"},
    "cpu-contention-co-tenant": {"noisy_neighbor"},
    "datastore-wait": {"slow_db"},
    "network-path-degradation": {"anomaly_net", "svc_net"},
    "host-disk-saturation": {"anomaly_disk"},
    "service-memory-cap": {"svc_mem_cap"},
}


def load_tasks(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = line.split()
        if len(p) >= 3:
            out[p[2]] = (p[0], p[1])
    return out


def build_reference(packs, truth, healthy="normal"):
    """median and MAD per (app, signal), from that deployment's own healthy runs.

    Per APPLICATION on purpose. The reference is what makes the score portable, so it has to be
    measured where the run was measured - that is the whole point. In a real deployment this is
    the service's own history rather than a `normal` family; here the dataset provides it.
    """
    vals = collections.defaultdict(list)
    for run, (app, fam) in truth.items():
        if fam != healthy or run not in packs:
            continue
        for name, get in SIGNALS.items():
            v = get(packs[run])
            if v is not None:
                vals[(app, name)].append(float(v))
    ref = {}
    for key, xs in vals.items():
        if len(xs) < 3:
            continue
        med = statistics.median(xs)
        mad = statistics.median([abs(x - med) for x in xs])
        scale = 1.4826 * mad                       # MAD -> sigma for a normal distribution
        floor = abs(med) * MAD_FLOOR_FRAC
        ref[key] = {"median": med, "sigma": max(scale, floor, 1e-9), "n": len(xs)}
    return ref


def z_profile(pack, app, ref):
    out = {}
    for name, get in SIGNALS.items():
        v = get(pack)
        r = ref.get((app, name))
        if v is None or r is None:
            out[name] = None
            continue
        out[name] = {"value": float(v),
                     "z": round((float(v) - r["median"]) / r["sigma"], 2),
                     "healthy_median": round(r["median"], 4)}
    return out


def match(profile, signature):
    """How much of a signature the profile shows, and the evidence for it.

    Three clause kinds, handled differently on purpose:

      "up"/"down"     positive evidence against HEALTHY. Earns score.
      "flat"          a VETO. Must hold or the whole signature fails; earns nothing. Absence of
                      a contradicting signal is not evidence for a diagnosis.
      ("gt", other)   this signal is more anomalous than `other`. Earns score. This is how "up,
                      but less up than the look-alike" is expressed with no magnitude.

    Unmeasurable signals are skipped rather than counted against, so a deployment that cannot
    produce one signal is not penalised for it - the failure mode that took datastore-wait to
    1/11 on Train Ticket, where all 40 Java services report under one comm.
    """
    hits, total, evidence, vetoed = 0.0, 0, [], None
    for key, spec in signature.items():
        if isinstance(key, tuple) and key[0] == "gt":
            # spec is the signal that must exceed key[1]
            a, b = profile.get(spec), profile.get(key[1])
            if a is None or b is None:
                continue
            total += 1
            ok = a["z"] > b["z"]
            hits += 1.0 if ok else 0.0
            evidence.append({"signal": f"{spec} vs {key[1]}", "expected": "more anomalous",
                             "z": round(a["z"] - b["z"], 2), "value": a["value"],
                             "healthy_median": a["healthy_median"], "satisfied": ok})
            continue

        name, direction = key, spec
        p = profile.get(name)
        if p is None:
            continue
        z = p["z"]
        if direction == "flat":
            ok = abs(z) < Z_ANOMALOUS
            if not ok and vetoed is None:
                vetoed = f"{name} moved {z:+.1f} sigma when this fault leaves it flat"
            evidence.append({"signal": name, "expected": "flat (veto)", "z": z,
                             "value": p["value"], "healthy_median": p["healthy_median"],
                             "satisfied": ok})
            continue

        total += 1
        signed = z if direction == "up" else -z
        strength = min(signed / Z_ANOMALOUS, 1.0) if signed > 0 else 0.0
        hits += strength
        evidence.append({"signal": name, "expected": direction, "z": z,
                         "value": p["value"], "healthy_median": p["healthy_median"],
                         "satisfied": signed >= Z_ANOMALOUS})
    score = round(hits / total, 3) if total else 0.0
    return {"score": 0.0 if vetoed else score, "raw_score": score,
            "n_signals": total, "vetoed": vetoed, "evidence": evidence}


def decide(pack, app, ref):
    profile = z_profile(pack, app, ref)
    scored = {name: match(profile, sig) for name, sig in SIGNATURES.items()}
    fired = [n for n, m in scored.items() if m["score"] >= MATCH_MIN and m["n_signals"] >= 2]
    fired.sort(key=lambda n: -scored[n]["score"])
    return {"profile": profile, "scored": scored, "fired": fired,
            "best": fired[0] if fired else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--agent-view", default="", help="print one run as an agent would see it")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    truth = load_tasks(a.tasks)
    packs = {}
    for run in truth:
        p = os.path.join(a.packs, f"{run}.json")
        if os.path.exists(p):
            packs[run] = json.load(open(p))

    ref = build_reference(packs, truth)

    if a.agent_view:
        run = a.agent_view
        app, fam = truth[run]
        d = decide(packs[run], app, ref)
        print(f"=== {run}  ({app}, collected as {fam}) ===")
        print("\nWhat the run measured, against this deployment's own healthy spread:\n")
        print(f"  {'signal':16s} {'value':>12s} {'healthy':>12s} {'sigma':>8s}")
        for name, p in d["profile"].items():
            if p is None:
                print(f"  {name:16s} {'not measured':>12s}")
            else:
                print(f"  {name:16s} {p['value']:12.4g} {p['healthy_median']:12.4g} "
                      f"{p['z']:+8.1f}")
        print("\nHow well each blueprint's expected pattern matches:\n")
        for n, m in sorted(d["scored"].items(), key=lambda kv: -kv[1]["score"]):
            mark = "  <== best match" if n == d["best"] else ""
            print(f"  {n:28s} score {m['score']:.2f} over {m['n_signals']} signals{mark}")
            if m.get("vetoed"):
                print(f"      VETOED: {m['vetoed']}")
            for e in m["evidence"]:
                tick = "yes" if e["satisfied"] else "no "
                print(f"      {tick}  {e['signal']:24s} expected {e['expected']:14s} "
                      f"got {e['z']:+.1f}")
        return 0

    # ---- score every run ------------------------------------------------------------------
    grid = collections.defaultdict(lambda: collections.defaultdict(list))
    per_app = collections.defaultdict(lambda: collections.defaultdict(list))
    n_fired = collections.Counter()
    rows = []
    for run, (app, fam) in sorted(truth.items()):
        if run not in packs:
            continue
        d = decide(packs[run], app, ref)
        n_fired[len(d["fired"])] += 1
        for bp in SIGNATURES:
            hit = bp in d["fired"]
            grid[bp][fam].append(hit)
            per_app[(bp, app)][fam].append(hit)
        rows.append({"run": run, "app": app, "family": fam, "fired": d["fired"],
                     "best": d["best"],
                     "scores": {k: v["score"] for k, v in d["scored"].items()}})

    print("=" * 78)
    print(f" PROFILE DECIDE on v2  -  {len(rows)} runs, kernel traces only")
    print(f" the only constants: Z_ANOMALOUS={Z_ANOMALOUS} sigma, MATCH_MIN={MATCH_MIN}")
    print(f" reference: median and MAD of each application's own `normal` runs")
    print("=" * 78)
    for bp in SIGNATURES:
        owns = OWNS[bp]
        pos = [h for fam in owns for h in grid[bp].get(fam, [])]
        neg = [h for fam, lst in grid[bp].items() if fam not in owns for h in lst]
        print(f"\n  {bp}   (owns {', '.join(sorted(owns))})")
        print(f"    recall      {sum(pos)}/{len(pos)}"
              + (f"  = {sum(pos)/len(pos):.0%}" if pos else ""))
        print(f"    false fires {sum(neg)}/{len(neg)}"
              + (f"  = {sum(neg)/len(neg):.0%}" if neg else ""))
        for fam in sorted(grid[bp]):
            n, tot = sum(grid[bp][fam]), len(grid[bp][fam])
            if fam in owns:
                flag = "" if n == tot else "   <-- misses"
            else:
                flag = "" if n == 0 else "   <-- FALSE FIRE"
            if n or fam in owns:
                print(f"      {fam:18s} {n:2d}/{tot:2d}{flag}")
        for app in ("sockshop", "trainticket"):
            k = (bp, app)
            if k not in per_app:
                continue
            t = [h for fam in owns for h in per_app[k].get(fam, [])]
            f_ = sum(h for fam, lst in per_app[k].items() if fam not in owns for h in lst)
            print(f"      [{app:11s}] recall {sum(t)}/{len(t)}, false fires {f_}")

    print("\n  how many blueprints fired per run:")
    for n in sorted(n_fired):
        label = {0: "none", 1: "exactly one"}.get(n, f"{n} - ambiguous")
        print(f"    {n_fired[n]:3d} runs  {label}")

    if a.out:
        json.dump({"reference": {f"{k[0]}|{k[1]}": v for k, v in ref.items()},
                   "constants": {"Z_ANOMALOUS": Z_ANOMALOUS, "MATCH_MIN": MATCH_MIN},
                   "rows": rows}, open(a.out, "w"), indent=2)
        print(f"\n  wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
