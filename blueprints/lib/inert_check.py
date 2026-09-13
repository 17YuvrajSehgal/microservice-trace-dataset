"""Which collected runs do NOT contain the fault they are labelled with?

READ THE WARNING AT THE BOTTOM BEFORE ACTING ON THE OUTPUT. A run flagged here is
a run whose own family signal sits in the healthy range FOR THE ONE SIGNAL CHOSEN
BELOW. That is not the same as the fault being absent. On Train Ticket this check
flags all 8 svc_cpu_cap runs and 9 of 11 slow_db runs, and every one of them does
contain its fault - the host-level signal simply cannot see one service among
forty that share a process name. Confirm with a second instrument (endpoint
latency) before calling any run bad. Full working: docs/RECOLLECT-list.md.

A run is INERT if its own family's deciding signal sits inside the healthy range. That is a
run we paid for and cannot use: the label says one thing and the trace shows nothing.

Only families whose deciding signal we have actually established are checked. The rest are
reported as "no established signal" rather than silently passing.
"""
import collections
import glob
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blueprint_decide as BD

PACKS = "/scratch/yuvraj17/stratatrace/results/v2-blueprints-all/packs"


def pr(p, k):
    return ((p.get("process") or {}).get("signature") or {}).get(k)


# family -> (label, how to read its own signal, direction)
SIGNALS = {
    "anomaly_cpu": ("host CPU at peak", lambda p: BD._cpu(p)["util_incident"], "high"),
    "noisy_neighbor": ("cores taken by a newcomer", lambda p: BD._cpu(p)["thief_cores"], "high"),
    "svc_cpu_cap": ("host CPU vs its own baseline", lambda p: BD._cpu(p)["util_ratio"], "low"),
    "anomaly_disk": ("disk requests per unit of interrupt rise",
                     lambda p: BD._io(p)["iops_per_irq"], "high"),
    "svc_mem_cap": ("device interrupt time", lambda p: BD._io(p)["hardirq_x"], "high"),
    "anomaly_mem": ("device interrupt time", lambda p: BD._io(p)["hardirq_x"], "high"),
    "slow_db": ("longest socket wait", lambda p: BD._blk(p)["max_socket_x"], "high"),
    "anomaly_net": ("retransmission %", lambda p: BD._net(p)["worst_retrans_pct"], "high"),
    "svc_net": ("retransmission %", lambda p: BD._net(p)["worst_retrans_pct"], "high"),
    "fork_storm": ("forks/s by a newcomer", lambda p: pr(p, "fork_newcomer_per_s"), "high"),
    "data_exfiltration": ("bytes/s by a newcomer",
                          lambda p: pr(p, "tx_newcomer_bytes_per_s"), "high"),
    "fd_exhaustion": ("EMFILE/s", lambda p: pr(p, "emfile_per_s_incident"), "high"),
    "dns_delay": ("EMFILE/s", lambda p: pr(p, "emfile_per_s_incident"), "high"),
}

vals = collections.defaultdict(list)
for f in sorted(glob.glob(os.path.join(PACKS, "*.json"))):
    try:
        p = json.load(io.open(f, encoding="utf-8"))
    except Exception:
        continue
    if not p.get("run_id"):
        continue
    fam = p.get("family_dir") or ""
    fam = fam[3:] if fam.startswith("tt_") else fam
    vals[(p.get("app"), fam)].append((p["run_id"], p))

# the healthy envelope, per application, for each signal we know
healthy = {}
for app in ("sockshop", "trainticket"):
    for fam, (lab, get, direction) in SIGNALS.items():
        xs = []
        for run, p in vals.get((app, "normal"), []):
            try:
                v = get(p)
            except Exception:
                v = None
            if v is not None:
                xs.append(v)
        if xs:
            healthy[(app, fam)] = (min(xs), max(xs))

print("%-22s %-12s %5s %-34s %s" % ("family", "app", "runs", "healthy range", "inert runs"))
print("-" * 108)
inert_total = 0
for (app, fam) in sorted(vals):
    if fam == "normal" or fam not in SIGNALS:
        continue
    lab, get, direction = SIGNALS[fam]
    h = healthy.get((app, fam))
    if not h:
        continue
    lo, hi = h
    bad = []
    for run, p in vals[(app, fam)]:
        try:
            v = get(p)
        except Exception:
            v = None
        if v is None:
            continue
        inside = (v <= hi) if direction == "high" else (v >= lo)
        if inside:
            bad.append((run, v))
    inert_total += len(bad)
    mark = "  <-- " + ", ".join("%s (%.4g)" % (r.split("_r")[-1] and "r" + r.split("_r")[-1], v)
                               for r, v in bad) if bad else ""
    print("%-22s %-12s %5d %-34s %d%s"
          % (fam, app, len(vals[(app, fam)]), "%.4g .. %.4g  (%s)" % (lo, hi, lab),
             len(bad), mark))

print()
print("total runs whose own signal sits inside the healthy range: %d" % inert_total)
print()
print("families with NO established deciding signal (not checked here):")
fams = sorted(set(f for (_, f) in vals if f not in SIGNALS and f != "normal"))
print("  " + ", ".join(fams))
