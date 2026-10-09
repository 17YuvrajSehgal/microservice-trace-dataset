#!/usr/bin/env python3
"""StrataTrace demo server - explore a trace, read the blueprints, watch the agent work.

Standard library only. No pip install, no build step, no network. It runs from a laptop with
the repo and demo/data present, which is the only thing that matters in a meeting room.

    python demo/app.py            # http://127.0.0.1:8765
    python demo/app.py --port N

WHAT IT SERVES

  /api/run          the trace: span, events, containers, per-container totals
  /api/timeline     one event counted across the recording
  /api/discriminate the blueprint's deciding check, computed live over a window you pick
  /api/blueprints   the blueprint library, and one blueprint's full text
  /api/analyze      the agent investigation, streamed step by step
  /api/truth        ground truth - served only when asked for, never used above

The first start does one pass over 4.1 million index rows and caches the aggregates, so it
takes about half a minute. Every start after that is instant.
"""
from __future__ import annotations
import argparse, glob, gzip, json, os, re, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(HERE, "data")
# The run catalog. A run appears in the app only once its index (<run_id>.tsv.gz) is present
# in demo/data/ - see available_runs(). The app starts and serves an empty state with none,
# so it never depends on data files existing. Add a run by building its index and adding an
# entry here (blueprint, ground-truth file, the signal/event the fault moves).
RUNS = {
    "svc_cpu_cap_aggressive_steady_r1": {
        "label": "One service's CPU cap",
        "blueprint": "service-cpu-throttle",
        "gt": "gt-svc_cpu_cap.json",
        "event": "sched_switch",
        "signal": "cpu",
        "note": "A 0.2-core CPU quota is imposed on one service (carts) for two minutes.",
    },
}


def available_runs():
    """Run ids whose index file is actually present. The app never assumes data exists -
    a run is offered only once its <run_id>.tsv.gz is in demo/data/."""
    return [rid for rid in RUNS
            if os.path.exists(os.path.join(DATA, rid + ".tsv.gz"))]


_env = os.environ.get("DEMO_RUN")
_av = available_runs()
RUN_ID = (_env if (_env in RUNS and _env in _av) else (_av[0] if _av else None))
CACHE = os.path.join(DATA, "aggregate-%s.json" % RUN_ID) if RUN_ID else None
RUN_DIR = os.path.join(DATA, "run", RUN_ID) if RUN_ID else None

TAB = chr(9)
HOST_NS = "4026531836"

# Event families the interface groups by. The network set is the one the blueprint's
# discriminator uses; the rest are there so a sceptic can check the others do NOT separate.
GROUPS = {
    "network": ("net_dev_xmit", "net_if_receive_skb", "net_dev_queue", "net_if_rx"),
    "cpu": ("sched_stat_runtime",),
    "sched": ("sched_switch", "sched_waking", "sched_wakeup"),
    "block": ("block_rq_issue", "block_rq_complete"),
}
_G = {ev: g for g, evs in GROUPS.items() for ev in evs}

STATE: dict = {}
LOCK = threading.Lock()


# ----------------------------------------------------------------------------------
# One pass over the index, cached.
# ----------------------------------------------------------------------------------
def build_aggregate(path: str) -> dict:
    ev_tot: dict = {}
    ev_sec: dict = {}          # event -> {second: count}
    ns_tot: dict = {}          # pid_ns -> {count, cpu_ns, procs{}}
    ns_grp: dict = {}          # (pid_ns, group) -> {second: [count, value]}
    lo = hi = None
    n = 0
    with gzip.open(path, "rt") as fh:
        for line in fh:
            if not line or line[0] == "#":
                continue
            f = line.rstrip(chr(10)).split(TAB)
            if len(f) < 6:
                continue
            t = float(f[0]); ev = f[1]; proc = f[2]; ns = f[3]
            c = int(f[4]); v = int(f[5])
            n += 1
            if lo is None or t < lo:
                lo = t
            if hi is None or t > hi:
                hi = t
            sec = int(t)
            ev_tot[ev] = ev_tot.get(ev, 0) + c
            d = ev_sec.setdefault(ev, {})
            d[sec] = d.get(sec, 0) + c
            r = ns_tot.setdefault(ns, {"count": 0, "cpu_ns": 0, "procs": {}})
            r["count"] += c
            if ev == "sched_stat_runtime":
                r["cpu_ns"] += v
            r["procs"][proc] = r["procs"].get(proc, 0) + c
            g = _G.get(ev)
            if g:
                k = ns + "|" + g
                gd = ns_grp.setdefault(k, {})
                cur = gd.get(sec)
                if cur is None:
                    gd[sec] = [c, v]
                else:
                    cur[0] += c; cur[1] += v
    for r in ns_tot.values():
        r["procs"] = dict(sorted(r["procs"].items(), key=lambda kv: -kv[1])[:8])
    return {
        "run_id": RUN_ID, "rows": n, "t0": lo, "t1": hi,
        "events": dict(sorted(ev_tot.items(), key=lambda kv: -kv[1])),
        "ev_sec": {k: {str(s): c for s, c in v.items()} for k, v in ev_sec.items()},
        "containers": ns_tot,
        "ns_grp": {k: {str(s): v for s, v in d.items()} for k, d in ns_grp.items()},
        "groups": {g: list(evs) for g, evs in GROUPS.items()},
    }


def load_state(rebuild=False, run_id=None):
    global RUN_ID, CACHE, RUN_DIR
    if run_id and run_id in RUNS:
        RUN_ID = run_id
        CACHE = os.path.join(DATA, "aggregate-%s.json" % RUN_ID)
        RUN_DIR = os.path.join(DATA, "run", RUN_ID)
    idx = os.path.join(DATA, RUN_ID + ".tsv.gz") if RUN_ID else None
    if not idx or not os.path.exists(idx):
        # No trace present. Serve an empty state rather than refusing to start.
        STATE.pop("agg", None); STATE.pop("lines", None); STATE.pop("run", None)
        return False
    if os.path.exists(CACHE) and not rebuild:
        print("loading cached aggregate ...", end=" ", flush=True)
        agg = json.load(open(CACHE, encoding="utf-8"))
        print("ok")
    else:
        print("first start: one pass over the index ...", end=" ", flush=True)
        t = time.time()
        agg = build_aggregate(idx)
        agg["run_id"] = RUN_ID
        json.dump(agg, open(CACHE, "w", encoding="utf-8"))
        print("%d rows in %.0f s" % (agg["rows"], time.time() - t))
    STATE["agg"] = agg
    STATE["lines"] = os.path.join(DATA, RUN_ID + ".lines.gz")
    STATE["run"] = RUNS[RUN_ID]
    # Deliberately NOT under the index root or the run directory: the code
    # sandbox is handed the index, and the answer should not sit beside it.
    gt = os.path.join(HERE, "answer", RUNS[RUN_ID]["gt"])
    STATE["truth"] = json.load(open(gt, encoding="utf-8")) if os.path.exists(gt) else {}
    # One recording per trace. A single shared file meant selecting the network trace and
    # pressing Replay showed the CPU investigation, scored against the wrong ground truth.
    tp = os.path.join(HERE, "demo-transcript-%s.jsonl" % RUN_ID)
    if not os.path.exists(tp):
        tp = os.path.join(HERE, "demo-transcript.jsonl")
    STATE["transcript"] = json.load(open(tp, encoding="utf-8", errors="replace")) \
        if os.path.exists(tp) else {}
    return True


def hms(s):
    s = float(s)
    return "%02d:%02d:%06.3f" % (int(s // 3600) % 24, int(s // 60) % 60, s % 60)


def secs(t):
    p = [float(x) for x in str(t).strip().split(":")]
    while len(p) < 3:
        p.insert(0, 0.0)
    return p[0] * 3600 + p[1] * 60 + p[2]


# ----------------------------------------------------------------------------------
# The blueprint's deciding check, computed live. This is the thing worth showing: the
# blueprint says "rank containers by how their traffic changed"; here you pick the windows
# and watch the ranking come out.
# ----------------------------------------------------------------------------------
def discriminate(group: str, b0: float, b1: float, i0: float, i1: float) -> dict:
    agg = STATE["agg"]
    use_value = (group == "cpu")
    out = []
    for key, d in agg["ns_grp"].items():
        ns, g = key.split("|")
        if g != group or ns == HOST_NS:
            continue
        base = inc = 0
        for s, cv in d.items():
            s = int(s)
            val = cv[1] if use_value else cv[0]
            if b0 <= s < b1:
                base += val
            elif i0 <= s < i1:
                inc += val
        if base + inc < 200:
            continue
        span_b = max(1.0, b1 - b0)
        span_i = max(1.0, i1 - i0)
        rb, ri = base / span_b, inc / span_i
        # A container that was not there before has no ratio - dividing by a zero baseline
        # produced 6.3e18 on the CPU trace, which is a number nobody can read. Flag it as
        # APPEARED and sort it to the top of the risers, where it belongs.
        appeared = rb < max(1e-9, ri * 0.01) and ri > 0
        out.append({
            "pid_ns": ns,
            "baseline": round(rb, 1), "incident": round(ri, 1),
            "ratio": None if appeared else round((ri + 1e-9) / (rb + 1e-9), 3),
            "appeared": appeared,
            "procs": list(agg["containers"].get(ns, {}).get("procs", {}))[:3],
        })
    # newcomers last: they have no ratio and are the extreme riser by definition
    out.sort(key=lambda r: (r["ratio"] is None, r["ratio"] if r["ratio"] is not None else 0))
    ranked = [r for r in out if r["ratio"] is not None]
    newcomers = [r for r in out if r["ratio"] is None]
    med = ranked[len(ranked) // 2]["ratio"] if len(ranked) > 2 else None
    lo = ranked[0] if ranked else None
    hi = (newcomers[0] if newcomers else (ranked[-1] if ranked else None))

    # BOTH ENDS, because which one is the culprit depends on the fault - and getting this
    # backwards is a real finding from the study, not a display nicety. A degraded network
    # path makes one container FALL. A CPU-saturating co-tenant is a newcomer that RISES. And
    # for a throttled container, ranking by the biggest fall puts the culprit at #15 of 18,
    # because when one service stalls the whole application slows and everyone else falls
    # further. The tab reports both and lets the reader see which end separates.
    def sep(r, against):
        if not r or not against or not r.get("ratio"):
            return None
        v = against / r["ratio"] if r["ratio"] < against else r["ratio"] / against
        return round(v, 1)

    return {
        "group": group, "unit": "CPU ns/s" if use_value else "events/s",
        "baseline_window": [hms(b0), hms(b1)], "incident_window": [hms(i0), hms(i1)],
        "rows": out,
        "lowest": lo, "highest": hi,
        "median_of_rest": med,
        "separation": sep(lo, med),
        "separation_up": sep(hi, med),
        "newcomer": bool(newcomers),
        "n_newcomers": len(newcomers),
    }


def raw_lines(event: str, t0: float, t1: float, limit: int = 12):
    out = []
    try:
        with gzip.open(STATE["lines"], "rt", errors="replace") as fh:
            for line in fh:
                if not line or line[0] == "#":
                    continue
                p = line.rstrip(chr(10)).split(TAB, 4)
                if len(p) < 5:
                    continue
                try:
                    t = float(p[0])
                except ValueError:
                    continue
                if t < t0 or t >= t1 or event not in p[1]:
                    continue
                out.append({"t": hms(t), "event": p[1], "procname": p[2],
                            "pid_ns": p[3], "raw": p[4]})
                if len(out) >= limit:
                    break
    except OSError:
        pass
    return out


# ----------------------------------------------------------------------------------
# Blueprints, read from the repo so the interface cannot drift from what the agent is given.
# ----------------------------------------------------------------------------------
SKILLS = os.path.join(ROOT, "blueprints", "skills-kernel-only")
PROBLEMS = os.path.join(ROOT, "blueprints", "problems")


def blueprint_list():
    out = []
    if not os.path.isdir(SKILLS):
        return out
    for f in sorted(os.listdir(SKILLS)):
        if not f.endswith(".md"):
            continue
        name = f[:-3]
        body = open(os.path.join(SKILLS, f), encoding="utf-8", errors="replace").read()
        m = re.search(r"^covers:\s*(.+)$", body, re.M)
        v = re.search(r"^version:\s*(\d+)$", body, re.M)
        sig = re.search(r"## When this applies\n(.+?)\n\n", body, re.S)
        out.append({
            "name": name,
            "covers": (m.group(1).strip() if m else ""),
            "version": int(v.group(1)) if v else None,
            "chars": len(body),
            "summary": (sig.group(1).strip().replace("\n", " ")[:190] if sig else ""),
            # which blueprint the SELECTED trace uses, not a hardcoded one - the tag
            # was sitting on the network blueprint while the CPU trace was loaded
            "active": bool(RUN_ID) and name == RUNS[RUN_ID]["blueprint"],
        })
    return out


def blueprint_body(name: str):
    p = os.path.join(SKILLS, re.sub(r"[^a-z0-9-]", "", name) + ".md")
    if not os.path.exists(p):
        return None
    body = open(p, encoding="utf-8", errors="replace").read()
    jp = os.path.join(PROBLEMS, os.path.basename(p)[:-3], "blueprint.json")
    meta = {}
    if os.path.exists(jp):
        try:
            d = json.load(open(jp, encoding="utf-8"))
            meta = {"capabilities": [c.get("id") if isinstance(c, dict) else c
                                     for c in d.get("capabilities_required", [])],
                    "steps": [s.get("step") for s in d.get("processing", [])],
                    "version": d.get("version")}
        except Exception:                                               # noqa: BLE001
            meta = {}
    return {"name": name, "body": body, "meta": meta}


# ----------------------------------------------------------------------------------
# The agent investigation, as a list of steps the interface plays back.
# ----------------------------------------------------------------------------------
def _digest(tool, res):
    """The few numbers that show what a tool call ACTUALLY returned.

    The interface used to show a tool call's arguments and nothing else, so the investigation
    read as a list of questions with no answers - and "how did it reach the verdict" was
    exactly the thing you could not see. The full result is up to 45 KB, which is unreadable
    on a screen, so this pulls out what a person would look at.
    """
    if not isinstance(res, dict):
        return None
    if res.get("error"):
        return {"error": str(res["error"])[:180]}
    try:
        if tool == "ctf_timespan":
            return {"recording": "%s to %s" % (res.get("begin"), res.get("end")),
                    "duration": "%s s" % res.get("duration_s")}
        if tool == "ctf_timeline":
            ser = res.get("series") or []
            ns = [int(b.get("n") or 0) for b in ser]
            d = {"total events": res.get("matched"), "buckets": len(ser)}
            if ns:
                lo, hi = min(ns), max(ns)
                d["per bucket"] = "%s low, %s high" % ("{:,}".format(lo), "{:,}".format(hi))
                if lo and hi / max(lo, 1) >= 2:
                    at = ser[ns.index(lo)].get("t", "")
                    d["biggest dip"] = "%sx, around %s" % (round(hi / max(lo, 1), 1), at[:8])
            return d
        if tool == "query_ctf":
            top = res.get("top_by_container") or []
            d = {"matched": res.get("matched"), "rate": "%s/s" % res.get("rate_per_s")}
            if top:
                t0 = top[0]
                d["busiest container"] = "%s (%s) %s events" % (
                    t0.get("pid_ns"), t0.get("procname"), "{:,}".format(t0.get("count") or 0))
            return d
        if tool == "ctf_proclife":
            return {"containers": res.get("n_containers_seen"),
                    "present only part of the recording":
                        len(res.get("present_for_only_part_of_the_recording") or []),
                    "present throughout": len(res.get("present_throughout") or [])}
        if tool == "ctf_procdiff":
            big = res.get("biggest_changes") or []
            d = {"only in range A": len(res.get("only_in_a") or []),
                 "only in range B": len(res.get("only_in_b") or []),
                 "rate A -> B": "%s/s -> %s/s" % (res.get("total_rate_a"),
                                                  res.get("total_rate_b"))}
            if big:
                b0 = big[0]
                d["biggest mover"] = "%s (%s)" % (b0.get("procname"), b0.get("pid_ns"))
            return d
        if tool == "ctf_lines":
            ls = res.get("lines") or []
            d = {"lines returned": res.get("returned"),
                 "of this many in range": res.get("total_in_range")}
            if ls:
                d["first line"] = str(ls[0])[:240]
            return d
    except Exception:                                                   # noqa: BLE001
        return None
    return None


def steps_from(ev, meta=None, final=None, head=True):
    """Turn transcript events into interface steps.

    Takes an event list rather than reading STATE, because the live run feeds it the same
    list while it is still growing. One conversion for both paths means the recording and a
    real run cannot drift apart in how they are presented.
    """
    meta = meta or {}
    steps = []
    if head:
        steps.append({"kind": "start", "title": "Investigation starts",
                      "body": "The agent is given the trace and seven read-only tools. It is "
                              "not told that an incident happened, when it was, or where to "
                              "look.",
                      "detail": {"started": meta.get("started_utc"),
                                 "incident": meta.get("incident_alias"),
                                 "model": meta.get("model"),
                                 "blueprint": meta.get("skill_given")}})
    for e in ev:
        t = e.get("type")
        if t == "plan":
            steps.append({"kind": "plan", "title": "It splits the work",
                          "body": "A planner writes independent subtasks; workers run them in "
                                  "parallel on their own tool threads.",
                          "detail": e.get("subtasks")})
        elif t == "tool_execution" and e.get("tool") != "run_python":
            who = str(e.get("node") or "")
            steps.append({"kind": "tool",
                          "title": ("%s -> %s" % (who, e.get("tool"))) if who
                                   else "Tool call: " + str(e.get("tool")),
                          "body": "",
                          "detail": {"arguments": e.get("arguments"),
                                     "node": e.get("node"),
                                     "returned": _digest(e.get("tool"), e.get("result")),
                                     "bytes": e.get("result_bytes")}})
        elif t == "finding":
            f = e.get("finding") or {}
            steps.append({"kind": "finding",
                          "title": ("%s -> finding" % e.get("node")) if e.get("node")
                                   else "Finding recorded",
                          "body": f.get("claim", ""),
                          "detail": {"where": f.get("where"), "when": f.get("when"),
                                     "evidence": f.get("evidence"),
                                     "confidence": f.get("confidence")}})
        elif t == "code_snippets":
            for s in (e.get("snippets") or []):
                r = s.get("result") or {}
                if not (r.get("stdout") or "").strip():
                    continue
                steps.append({"kind": "code",
                              "title": ("%s -> wrote and ran its own code" % s.get("node"))
                                       if s.get("node") else "It writes and runs its own code",
                              "body": s.get("why") or "",
                              "detail": {"code": s.get("code"),
                                         "stdout": (r.get("stdout") or "")[:2600]}})
    fin = (final or {}).get("diagnosis") or {}
    if fin:
        steps.append({"kind": "verdict", "title": "It commits to an answer",
                      "body": fin.get("what_is_wrong", ""), "detail": fin})
    return steps


def analysis_steps():
    d = STATE.get("transcript") or {}
    steps = steps_from(d.get("events", []), d.get("meta"), d.get("final"))
    # tool calls are numerous and low-information one at a time; keep a sample in the replay
    keep, seen = [], 0
    for s in steps:
        if s["kind"] == "tool":
            seen += 1
            if seen % 4 != 1:
                continue
        keep.append(s)
    return keep


def _score_diagnosis(dx):
    """Score a diagnosis with the study's own scorer, not a demo-only copy.

    Imported lazily and from blueprints/lib so the numbers on screen are produced by exactly
    the code that produced the published results. Returns {} if the scorer cannot be loaded,
    rather than inventing something.
    """
    try:
        import importlib.util
        sys.path.insert(0, os.path.join(ROOT, "blueprints", "lib"))
        sys.path.insert(0, os.path.join(ROOT, "agentic-rca"))
        spec = importlib.util.spec_from_file_location(
            "q2one", os.path.join(ROOT, "blueprints", "lib", "q2_run_one.py"))
        one = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(one)
        except SystemExit:
            pass
        import q2_judge as J
        gt_full = STATE.get("truth") or {}
        f = gt_full.get("fault") or {}
        problem = "anomaly_cpu" if RUN_ID.startswith("anomaly_cpu") else "svc_net"
        w = J.score_where(dx.get("root_cause_service", ""), dx.get("culprit_kind", ""),
                          problem, true_service=f.get("target_service", ""),
                          scope=f.get("scope", ""), true_ns=f.get("target_pid_ns", ""))
        win = one.score_window(dx.get("incident_window"), gt_full)
        return {"where": w.get("where"), "container_correct": w.get("container_correct"),
                "pred_pid_ns": w.get("pid_ns"), "true_pid_ns": w.get("true_pid_ns"),
                "window_verdict": win.get("verdict"), "window_iou": win.get("iou")}
    except Exception:                                                   # noqa: BLE001
        return {}


def score_block():
    # After a real run, score THAT run. Showing the recording's score next to a live verdict
    # would be quietly wrong - the two are different investigations.
    out = LIVE.get("out") if LIVE.get("done") else None
    dx = (out or {}).get("diagnosis") if out else None
    if dx:
        sc = _score_diagnosis(dx)
        if sc:
            sc["of"] = "the run you just watched"
            return {"score": sc, "truth": (STATE.get("truth") or {}).get("fault", {})}
    d = STATE.get("transcript") or {}
    sc = dict(d.get("_score") or {})
    if sc:
        sc["of"] = "the replayed run"
    return {"score": sc, "truth": (STATE.get("truth") or {}).get("fault", {})}


# ----------------------------------------------------------------------------------
# A REAL run.
#
# This is the part that makes the demo a demo rather than a recording. It calls the same
# agent_v2.diagnose the study calls, on the same index the agent's tools read, with the same
# blueprint. Nothing about the agent is changed or wrapped for the occasion.
#
# Progress is observed by polling the agent's own Transcript object while it fills. That
# object is exactly what gets written to disk at the end, so the interface is watching the
# audit record being produced rather than a parallel narration built for the screen - and the
# agent needs no callback, no hook, and no demo-only branch.
# ----------------------------------------------------------------------------------
LIVE = {"running": False, "error": None, "started": 0.0, "done": False,
        "out": None, "tr": None, "seen": 0, "head": False, "stopped": False}
LIVE_LOCK = threading.Lock()


def live_ready():
    """Can a real run happen here? Report every reason it cannot, not just the first."""
    why = []
    for m in ("openai", "langgraph", "pandas", "dotenv"):
        try:
            __import__(m)
        except Exception:                                               # noqa: BLE001
            why.append("missing package: " + m)
    if not RUN_DIR or not os.path.isdir(RUN_DIR):
        why.append("no trace loaded — add an index to demo/data/ to run an investigation")
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
    except Exception:                                                   # noqa: BLE001
        pass
    prov = (os.environ.get("RCA_PROVIDER") or "").lower()
    keyvar = {"azure": "AZURE_OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
              "openai": "OPENAI_API_KEY", "openrouter": "OPEN_ROUTER_API_KEY"}.get(prov, "")
    has_key = bool((os.environ.get(keyvar) or "").strip()) or (
        prov == "openrouter" and (os.environ.get("OPENROUTER_API_KEY") or "").strip())
    if keyvar and not has_key:
        why.append("no API key for provider %r" % prov)
    return {"ready": not why, "why": why,
            "provider": prov or "unset", "model": os.environ.get("RCA_MODEL") or "unset"}


def _live_worker():
    try:
        os.environ["CTF_INDEX_ROOT"] = DATA
        sys.path.insert(0, os.path.join(ROOT, "agentic-rca"))
        sys.path.insert(0, ROOT)
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
        from stratatrace import load_run
        import agent_v2, skillreg
        sk = [x for x in skillreg.load_skills(
            os.path.join(ROOT, "blueprints", "skills-kernel-only"))
            if x.name == RUNS[RUN_ID]["blueprint"]]

        # CLEAR IT FIRST. agent_v2.CTX is a module global that outlives a run, so on a second
        # run the watcher below latched onto the PREVIOUS run's context immediately and the
        # interface replayed all of its old steps before a single new one arrived. Nulling it
        # makes the watcher wait for the context this run creates.
        prev = getattr(agent_v2, "CTX", None)
        agent_v2.CTX = None

        def watch():
            # agent_v2 sets its module-global CTX once diagnose() starts
            for _ in range(2400):
                c = getattr(agent_v2, "CTX", None)
                if c is not None and c is not prev and getattr(c, "tr", None) is not None:
                    LIVE["tr"] = c.tr
                    return
                time.sleep(0.25)
        threading.Thread(target=watch, daemon=True).start()
        out = agent_v2.diagnose(load_run(RUN_DIR), app="sockshop",
                                transcript_path=os.path.join(DATA, "live.json"),
                                condition="demo-live", skills=sk, skill_given=True)
        LIVE["out"] = out
        # Every finished run becomes a session on disk, so a refresh or restart loses
        # nothing: the transcript replays, and the chat continues where it stopped.
        tr = LIVE.get("tr")
        if out and tr is not None:
            sid = time.strftime("%Y%m%d-%H%M%S")
            _sess_write({"id": sid, "run_id": RUN_ID, "created": time.time(),
                         "meta": dict(getattr(tr, "meta", {}) or {}),
                         "out": out, "run_events": list(tr.events),
                         "chat": {"msgs": [], "turn": 0, "events": []}})
            CHAT.update({"sid": sid, "obj": None, "base_events": []})
    except Exception as e:                                              # noqa: BLE001
        LIVE["error"] = "%s: %s" % (type(e).__name__, e)
    finally:
        LIVE["done"] = True
        LIVE["running"] = False


def live_start():
    with LIVE_LOCK:
        if LIVE["running"]:
            return {"started": False, "reason": "a run is already in progress"}
        r = live_ready()
        if not r["ready"]:
            return {"started": False, "reason": "; ".join(r["why"])}
        LIVE.update({"running": True, "error": None, "started": time.time(),
                     "done": False, "out": None, "tr": None, "seen": 0,
                     "head": False, "stopped": False})
        # chat is grounded in a specific run's verdict; a new run makes the old seed stale
        if CHAT.get("obj") is not None:
            try:
                CHAT["obj"].close()
            except Exception:                                           # noqa: BLE001
                pass
        CHAT.update({"obj": None, "busy": False, "error": None,
                     "sid": None, "base_events": []})
    threading.Thread(target=_live_worker, daemon=True).start()
    return {"started": True}


def live_stop():
    """Ask an in-flight run to stop.

    Sets the agent's own cancel flag rather than killing a thread: the run then raises at its
    next model call, diagnose() records the error and writes the transcript as it always does,
    so a stopped run leaves the same audit trail as a finished one.
    """
    if not LIVE["running"]:
        return {"stopped": False, "reason": "nothing is running"}
    try:
        sys.path.insert(0, os.path.join(ROOT, "agentic-rca"))
        import agent_v2
        agent_v2.CANCEL.set()
        LIVE["stopped"] = True
        return {"stopped": True}
    except Exception as e:                                              # noqa: BLE001
        return {"stopped": False, "reason": "%s: %s" % (type(e).__name__, e)}


def live_poll(since: int):
    tr = LIVE.get("tr")
    ev = list(getattr(tr, "events", []) or []) if tr is not None else []
    new = ev[since:]
    want_head = not LIVE["head"]
    steps = steps_from(new, getattr(tr, "meta", {}) or {},
                       (LIVE.get("out") or {}) if LIVE["done"] else None,
                       head=want_head)
    if want_head:
        LIVE["head"] = True
    if LIVE["done"] and LIVE.get("out"):
        d = (LIVE["out"] or {}).get("diagnosis") or {}
        if d and not any(s["kind"] == "verdict" for s in steps):
            steps.append({"kind": "verdict", "title": "It commits to an answer",
                          "body": d.get("what_is_wrong", ""), "detail": d})
    # Never blank. The first few seconds are setup events that match none of the interesting
    # cases, and an empty status next to a spinner reads as "stuck" rather than "starting".
    _SAY = {"tool_execution": None,          # filled in below, it names the tool
            "finding": "recording a finding",
            "plan": "planning the investigation",
            "api_response": "thinking",
            "skill_injected": "reading the blueprint",
            "system_prompt": "reading its instructions",
            "user_message": "reading the task",
            "shared_context": "opening the trace"}
    now = "starting" if not ev else "working"
    for e in reversed(ev):
        t = e.get("type")
        if t == "tool_execution":
            now = "calling " + str(e.get("tool"))
            break
        if t in _SAY and _SAY[t]:
            now = _SAY[t]
            break
    return {"steps": steps, "cursor": len(ev), "doing": now, "events": len(ev),
            "running": LIVE["running"], "done": LIVE["done"],
            "error": LIVE["error"], "stopped": LIVE["stopped"],
            "elapsed": round(time.time() - LIVE["started"], 1) if LIVE["started"] else 0,
            "summary": {k: (LIVE.get("out") or {}).get(k)
                        for k in ("wall_s", "n_tool_calls", "n_code_snippets",
                                  "n_findings", "tokens")} if LIVE["done"] else None}


# ----------------------------------------------------------------------------------
# Ask the agent. After a live run commits to a verdict, follow-up questions go to
# agent_v2.Chat - the same tools, recorded in a transcript of its own, which the UI polls
# exactly the way it polls the run. Seeded with what THAT run found, so "why did you say
# carts?" is answerable; a question needing fresh data triggers real tool calls.
# ----------------------------------------------------------------------------------
CHAT = {"obj": None, "busy": False, "error": None, "t0": 0.0,
        "sid": None, "base_events": []}
CHAT_LOCK = threading.Lock()

# One file per session: the run (its transcript + verdict) and the whole conversation held
# about it. A session is the unit of persistence AND the unit of context - resuming one
# restores its message thread verbatim, and no session ever sees another's.
SESS_DIR = os.path.join(DATA, "sessions")
os.makedirs(SESS_DIR, exist_ok=True)


def _sess_path(sid):
    return os.path.join(SESS_DIR, re.sub(r"[^0-9A-Za-z_-]", "", sid) + ".json")


def _sess_load(sid):
    try:
        return json.load(open(_sess_path(sid), encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _sess_write(sess):
    tmp = _sess_path(sess["id"]) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(sess, fh, default=str)
    os.replace(tmp, _sess_path(sess["id"]))


def save_chat():
    """Fold the in-memory conversation back into its session file."""
    sid, obj = CHAT.get("sid"), CHAT.get("obj")
    if not sid or obj is None:
        return
    sess = _sess_load(sid)
    if not sess:
        return
    snap = obj.snapshot()
    sess["chat"] = {"msgs": snap["msgs"], "turn": snap["turn"],
                    "events": (CHAT.get("base_events") or []) + list(obj.ctx.tr.events)}
    _sess_write(sess)


def session_fork(sid):
    """A fresh conversation about the SAME stored run - the run cost minutes, a chat is free.

    Copies the run data into a new session with an empty chat, so the new thread starts from
    the verdict seed alone and the old conversation stays untouched in its own file."""
    if LIVE["running"]:
        return {"error": "a live run is in progress"}
    if CHAT["busy"]:
        return {"error": "still answering a question"}
    src = _sess_load(sid)
    if not src:
        return {"error": "no such session"}
    nid = time.strftime("%Y%m%d-%H%M%S")
    while os.path.exists(_sess_path(nid)):
        nid += "b"
    _sess_write({"id": nid, "run_id": src.get("run_id"), "created": time.time(),
                 "meta": src.get("meta"), "out": src.get("out"),
                 "run_events": src.get("run_events"), "forked_from": sid,
                 "code_root": src.get("code_root"),
                 "chat": {"msgs": [], "turn": 0, "events": []}})
    return session_open(nid)


def code_browse():
    """Open the OS folder picker on the machine running the server; return the chosen path."""
    pick = chr(10).join([
        "import tkinter as tk",
        "from tkinter import filedialog",
        "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)",
        "p = filedialog.askdirectory(title='Select the application source directory')",
        "print(p or '')",
    ])
    try:
        out = subprocess.run([sys.executable, "-c", pick], capture_output=True,
                             text=True, timeout=180)
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"error": "could not open a folder dialog: %s" % e}
    path = (out.stdout or "").strip().splitlines()[-1:] or [""]
    path = path[0].strip()
    if not path:
        return {"path": None}                      # user cancelled
    if not os.path.isdir(path):
        return {"error": "not a directory: %s" % path}
    return {"path": path}


def code_connect(path):
    """Attach a local source directory to the CURRENT session, read-only."""
    sid = CHAT.get("sid")
    if not sid:
        return {"error": "open or run a session first"}
    if CHAT["busy"]:
        return {"error": "still answering a question"}
    sess = _sess_load(sid)
    if not sess:
        return {"error": "no such session"}
    if not path:                                   # disconnect
        sess.pop("code_root", None)
    else:
        sys.path.insert(0, os.path.join(ROOT, "agentic-rca"))
        import coderepo
        try:
            repo = coderepo.CodeRepo(path)
        except ValueError as e:
            return {"error": str(e)}
        n = len(repo.call("code_tree", {"depth": 4}).get("entries") or [])
        sess["code_root"] = repo.root
    # keep the conversation, drop the object: the next ask rebuilds it with the code tools
    if CHAT.get("obj") is not None:
        save_chat()
        sess = _sess_load(sid)                     # re-read: save_chat rewrote the file
        if path:
            sess["code_root"] = repo.root
        else:
            sess.pop("code_root", None)
        try:
            CHAT["obj"].close()
        except Exception:                          # noqa: BLE001
            pass
        CHAT["obj"] = None
        CHAT["base_events"] = list((sess.get("chat") or {}).get("events") or [])
    _sess_write(sess)
    if not path:
        return {"connected": None}
    return {"connected": sess["code_root"], "entries_seen": n}


def sessions_list():
    out = []
    for f in sorted(glob.glob(os.path.join(SESS_DIR, "*.json")), reverse=True):
        try:
            sess = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        d = (sess.get("out") or {}).get("diagnosis") or {}
        out.append({"id": sess.get("id"), "run_id": sess.get("run_id"),
                    "created": sess.get("created"),
                    "where": d.get("root_cause_service"),
                    "turns": (sess.get("chat") or {}).get("turn") or 0})
    return {"sessions": out}


def session_open(sid):
    """Make a stored session current: its steps for the screen, its thread for the chat."""
    if LIVE["running"]:
        return {"error": "a live run is in progress - stop it or let it finish first"}
    if CHAT["busy"]:
        return {"error": "still answering a question"}
    sess = _sess_load(sid)
    if not sess:
        return {"error": "no such session"}
    if CHAT.get("obj") is not None:
        try:
            CHAT["obj"].close()
        except Exception:                                               # noqa: BLE001
            pass
    CHAT.update({"sid": sess["id"], "obj": None, "error": None,
                 "base_events": list((sess.get("chat") or {}).get("events") or [])})
    steps = steps_from(sess.get("run_events") or [], sess.get("meta") or {},
                       sess.get("out") or {}, head=True)
    d = (sess.get("out") or {}).get("diagnosis") or {}
    if d and not any(st["kind"] == "verdict" for st in steps):
        steps.append({"kind": "verdict", "title": "It commits to an answer",
                      "body": d.get("what_is_wrong", ""), "detail": d})
    return {"id": sess["id"], "run_id": sess.get("run_id"),
            "code_root": sess.get("code_root"),
            "run_steps": steps,
            "chat_steps": chat_steps_from(CHAT["base_events"]), "ready": True}


def chat_ask(q: str):
    if not q.strip():
        return {"accepted": False, "reason": "empty question"}
    if LIVE["running"]:
        return {"accepted": False, "reason": "wait for the run to finish"}
    if not CHAT.get("sid"):
        return {"accepted": False,
                "reason": "run the agent, or open a past session - chat is grounded in one"}
    with CHAT_LOCK:
        if CHAT["busy"]:
            return {"accepted": False, "reason": "still answering the previous question"}
        CHAT["busy"], CHAT["error"] = True, None
        CHAT["t0"] = time.time()

    def work():
        try:
            os.environ["CTF_INDEX_ROOT"] = DATA
            sys.path.insert(0, os.path.join(ROOT, "agentic-rca"))
            sys.path.insert(0, ROOT)
            from stratatrace import load_run
            import agent_v2, skillreg
            if CHAT["obj"] is None:
                sess = _sess_load(CHAT["sid"]) or {}
                rid = sess.get("run_id") or RUN_ID
                rd = os.path.join(DATA, "run", rid)
                sk = [x for x in skillreg.load_skills(
                    os.path.join(ROOT, "blueprints", "skills-kernel-only"))
                    if x.name == RUNS.get(rid, {}).get("blueprint")]
                snap = sess.get("chat") or {}
                croot = sess.get("code_root")
                if snap.get("msgs"):
                    # resume: the stored thread is the whole context, verbatim
                    CHAT["obj"] = agent_v2.Chat(load_run(rd), app="sockshop",
                                                skill=sk[0] if sk else None,
                                                restore=snap, code_root=croot)
                else:
                    # first question in this session: seed from the stored run
                    rev = sess.get("run_events") or []
                    dx = (sess.get("out") or {}).get("diagnosis")
                    find = next((e.get("findings") for e in reversed(rev)
                                 if e.get("type") == "scratchpad"), None)
                    comp = next((e.get("computed") for e in reversed(rev)
                                 if e.get("type") == "computed"), None)
                    CHAT["obj"] = agent_v2.Chat(load_run(rd), app="sockshop",
                                                skill=sk[0] if sk else None, diagnosis=dx,
                                                findings=find, computed=comp,
                                                code_root=croot)
            CHAT["obj"].ask(q)
            save_chat()
        except Exception as e:                                          # noqa: BLE001
            CHAT["error"] = "%s: %s" % (type(e).__name__, e)
        finally:
            CHAT["busy"] = False
    threading.Thread(target=work, daemon=True).start()
    return {"accepted": True}


def chat_steps_from(events):
    """Chat transcript events -> interface steps, in event order. steps_from is per-event
    stateless, so feeding it one event at a time changes nothing but the order."""
    steps = []
    for e in events:
        t = e.get("type")
        if t == "chat_question":
            steps.append({"kind": "question", "title": "You ask", "body": e.get("text", "")})
        elif t == "chat_answer":
            steps.append({"kind": "answer", "title": "It answers", "body": e.get("text", "")})
        else:
            steps.extend(steps_from([e], {}, None, head=False))
        # steps_from leaves run_python to the end-of-run code_snippets event, which chat
        # never emits - so show the code here, straight from the execution event.
        if t == "tool_execution" and e.get("tool") == "run_python":
            r = e.get("result") or {}
            steps.append({"kind": "code", "title": "It writes and runs its own code",
                          "body": (e.get("arguments") or {}).get("why") or "",
                          "detail": {"code": (e.get("arguments") or {}).get("code") or "",
                                     "stdout": r.get("stdout") or r.get("error") or ""}})
        # A run_python snippet may carry a chart: codetool hoists a "PLOT {json}" stdout
        # line into result.plot, whole - the capped stdout copy would cut a 600-point series.
        if t == "tool_execution" and e.get("tool") == "run_python":
            raw = (e.get("result") or {}).get("plot")
            if raw:
                try:
                    spec = json.loads(raw)
                    steps.append({"kind": "plot", "title": spec.get("title") or "Chart",
                                  "detail": spec})
                except ValueError:
                    pass
    return steps


def chat_poll(since: int):
    c = CHAT.get("obj")
    ev = list(getattr(c.ctx.tr, "events", []) or []) if c is not None else []
    steps = chat_steps_from(ev[since:])
    doing = "thinking"
    for e in reversed(ev):
        t = e.get("type")
        if t == "tool_execution":
            doing = ("running its own code, thinking about the result"
                     if e.get("tool") == "run_python"
                     else "ran %s, thinking about the result" % e.get("tool"))
            break
        if t == "api_response":
            doing = "acting on the model's reply"
            break
        if t == "chat_question":
            break
    return {"steps": steps, "cursor": len(ev), "busy": CHAT["busy"], "doing": doing,
            "elapsed": round(time.time() - CHAT.get("t0", time.time()), 1),
            "error": CHAT["error"],
            "ready": bool(CHAT.get("sid")) and not LIVE["running"]}


# ----------------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------------
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):                                          # quiet
        pass

    def _send(self, body: bytes, ctype="application/json"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj):
        self._send(json.dumps(obj, default=str).encode("utf-8"))

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        p = u.path
        try:
            if p in ("/", "/index.html"):
                f = os.path.join(HERE, "ui.html")
                return self._send(open(f, "rb").read(), "text/html; charset=utf-8")
            if p == "/api/run":
                if not STATE.get("agg"):
                    return self._json({"empty": True, "runs": available_runs()})
                a = STATE["agg"]
                cs = []
                for ns, r in sorted(a["containers"].items(), key=lambda kv: -kv[1]["count"]):
                    cs.append({"pid_ns": ns, "events": r["count"],
                               "cpu_s": round(r["cpu_ns"] / 1e9, 1),
                               "procs": list(r["procs"])[:5],
                               "is_host": ns == HOST_NS})
                top = list(a["events"].items())[:40]
                return self._json({
                    "run_id": a["run_id"], "rows": a["rows"],
                    "begin": hms(a["t0"]), "end": hms(a["t1"]),
                    "duration_s": round(a["t1"] - a["t0"], 1),
                    "meta": STATE.get("run") or {},
                    "n_events": len(a["events"]), "n_containers": len(cs),
                    "events": [{"event": e, "count": c} for e, c in top],
                    "containers": cs, "groups": a["groups"],
                })
            if p == "/api/timeline":
                if not STATE.get("agg"):
                    return self._json({"empty": True})
                ev = (q.get("event") or ["sched_switch"])[0]
                a = STATE["agg"]
                d = a["ev_sec"].get(ev) or {}
                t0, t1 = int(a["t0"]), int(a["t1"])
                series = [{"t": hms(s), "s": s, "n": d.get(str(s), 0)}
                          for s in range(t0, t1 + 1)]
                return self._json({"event": ev, "series": series,
                                   "total": a["events"].get(ev, 0)})
            if p == "/api/discriminate":
                if not STATE.get("agg"):
                    return self._json({"empty": True})
                g = (q.get("group") or ["network"])[0]
                a = STATE["agg"]
                t0, t1 = a["t0"], a["t1"]
                b0 = float((q.get("b0") or [t0 + 5])[0])
                b1 = float((q.get("b1") or [t0 + 50])[0])
                i0 = float((q.get("i0") or [t0 + 60])[0])
                i1 = float((q.get("i1") or [t0 + 180])[0])
                return self._json(discriminate(g, b0, b1, i0, i1))
            if p == "/api/lines":
                if not STATE.get("agg"):
                    return self._json({"empty": True, "lines": []})
                ev = (q.get("event") or ["net_if_receive_skb"])[0]
                a = STATE["agg"]
                t0 = float((q.get("t0") or [a["t0"] + 100])[0])
                return self._json({"lines": raw_lines(ev, t0, t0 + 3)})
            if p == "/api/blueprints":
                return self._json({"blueprints": blueprint_list()})
            if p == "/api/blueprint":
                b = blueprint_body((q.get("name") or [""])[0])
                return self._json(b or {"error": "not found"})
            if p == "/api/analyze":
                return self._json({"steps": analysis_steps()})
            if p == "/api/runs":
                av = set(available_runs())
                return self._json({"current": RUN_ID,
                                   "runs": [dict(RUNS[k], id=k) for k in RUNS if k in av]})
            if p == "/api/select":
                rid = (q.get("run") or [""])[0]
                if rid in RUNS and rid in available_runs() and rid != RUN_ID:
                    with LOCK:
                        load_state(False, rid)
                return self._json({"current": RUN_ID})
            if p == "/api/live/ready":
                return self._json(live_ready())
            if p == "/api/live/start":
                return self._json(live_start())
            if p == "/api/live/stop":
                return self._json(live_stop())
            if p == "/api/sessions":
                return self._json(sessions_list())
            if p == "/api/code/browse":
                return self._json(code_browse())
            if p == "/api/code/connect":
                return self._json(code_connect((q.get("path") or [""])[0]))
            if p == "/api/session/fork":
                return self._json(session_fork((q.get("id") or [""])[0]))
            if p == "/api/session":
                return self._json(session_open((q.get("id") or [""])[0]))
            if p == "/api/chat/ask":
                return self._json(chat_ask((q.get("q") or [""])[0]))
            if p == "/api/chat/poll":
                return self._json(chat_poll(int((q.get("since") or ["0"])[0])))
            if p == "/api/live/poll":
                return self._json(live_poll(int((q.get("since") or ["0"])[0])))
            if p == "/api/results":
                # Derived once from the scored cells and shipped as a small file: the full
                # results tree is ~220 MB and is not in the repo, so the demo cannot compute
                # this on another machine. demo/results.json records how it was derived.
                f = os.path.join(HERE, "results.json")
                if not os.path.exists(f):
                    return self._json({"error": "demo/results.json is missing"})
                return self._json(json.load(open(f, encoding="utf-8")))
            if p == "/api/truth":
                return self._json(score_block())
            self.send_error(404)
        except Exception as e:                                          # noqa: BLE001
            self._json({"error": "%s: %s" % (type(e).__name__, e)})


def main() -> int:
    # Load the provider config once, at startup. It used to load inside the live-run path
    # only, so a server that went straight to chat fell back to the default provider.
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
    except ImportError:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--rebuild", action="store_true", help="discard the cached aggregate")
    a = ap.parse_args()
    loaded = load_state(a.rebuild)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    print()
    print("  StrataTrace   ->   http://127.0.0.1:%d" % a.port)
    if loaded:
        print("  run %s   %s events over %.0f s   %d containers"
              % (RUN_ID, "{:,}".format(STATE["agg"]["rows"]),
                 STATE["agg"]["t1"] - STATE["agg"]["t0"], len(STATE["agg"]["containers"])))
    else:
        print("  no trace loaded - add an index to demo/data/ and refresh, or just")
        print("  connect a code repo and review past sessions on the Agent tab")
    print("  ctrl-c to stop")
    print()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
