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
import argparse, gzip, json, os, re, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(HERE, "data")
# Two traces, chosen for opposite reasons.
#
# anomaly_cpu is what we are most confident about - 55 of 60 on WHERE in the published study -
# so a LIVE run on it is very likely to succeed and is the safe one to show people.
#
# svc_net is our hardest: 0 of 60 published, 10 of 30 after this week's fixes. A live run on it
# is roughly a one-in-three. It is here because it is the more interesting conversation, not
# because it performs - and the interface says so rather than letting someone assume otherwise.
RUNS = {
    "anomaly_cpu_aggressive_steady_r1": {
        "label": "Host CPU saturation",
        "blueprint": "host-cpu-saturation",
        "gt": "gt-anomaly_cpu.json",
        "published": "55/60 found the right component",
        "confidence": "high",
        "note": "A co-tenant workload saturates the host's CPU for two minutes.",
    },
    "svc_net_aggressive_steady_r3": {
        "label": "One service's network path",
        "blueprint": "network-path-degradation",
        "gt": "gt-svc_net.json",
        "published": "0/60 published, 10/30 after this week's fixes",
        "confidence": "low",
        "note": "150 ms delay, 40 ms jitter and 4% packet loss on one container's "
                "network interface for two minutes.",
    },
}
RUN_ID = os.environ.get("DEMO_RUN", "anomaly_cpu_aggressive_steady_r1")
if RUN_ID not in RUNS:
    RUN_ID = "anomaly_cpu_aggressive_steady_r1"
CACHE = os.path.join(DATA, "aggregate-%s.json" % RUN_ID)
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
    idx = os.path.join(DATA, RUN_ID + ".tsv.gz")
    if not os.path.exists(idx):
        print("MISSING %s\n  run demo/fetch_data.sh first" % idx)
        sys.exit(1)
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
    tp = os.path.join(HERE, "demo-transcript.jsonl")
    STATE["transcript"] = json.load(open(tp, encoding="utf-8", errors="replace")) \
        if os.path.exists(tp) else {}


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
        out.append({
            "pid_ns": ns,
            "baseline": round(rb, 1), "incident": round(ri, 1),
            "ratio": round((ri + 1e-9) / (rb + 1e-9), 3),
            "procs": list(agg["containers"].get(ns, {}).get("procs", {}))[:3],
        })
    out.sort(key=lambda r: r["ratio"])
    med = out[len(out) // 2]["ratio"] if len(out) > 2 else None
    return {
        "group": group, "unit": "CPU ns/s" if use_value else "events/s",
        "baseline_window": [hms(b0), hms(b1)], "incident_window": [hms(i0), hms(i1)],
        "rows": out,
        "lowest": out[0] if out else None,
        "median_of_rest": med,
        "separation": round(med / out[0]["ratio"], 1) if out and med and out[0]["ratio"] else None,
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
            "active": name == "network-path-degradation",
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
                      "detail": {"incident": meta.get("incident_alias"),
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
                          "body": "", "detail": {"arguments": e.get("arguments"),
                                                 "node": e.get("node")}})
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


def score_block():
    d = STATE.get("transcript") or {}
    return {"score": d.get("_score") or {}, "truth": (STATE.get("truth") or {}).get("fault", {})}


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
RUN_DIR = os.path.join(DATA, "run", RUN_ID)


def live_ready():
    """Can a real run happen here? Report every reason it cannot, not just the first."""
    why = []
    for m in ("openai", "langgraph", "pandas", "dotenv"):
        try:
            __import__(m)
        except Exception:                                               # noqa: BLE001
            why.append("missing package: " + m)
    if not os.path.isdir(RUN_DIR):
        why.append("no run directory at " + RUN_DIR)
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
    except Exception:                                                   # noqa: BLE001
        pass
    prov = (os.environ.get("RCA_PROVIDER") or "").lower()
    keyvar = {"azure": "AZURE_OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
              "openai": "OPENAI_API_KEY"}.get(prov, "")
    if keyvar and not (os.environ.get(keyvar) or "").strip():
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
                ev = (q.get("event") or ["sched_switch"])[0]
                a = STATE["agg"]
                d = a["ev_sec"].get(ev) or {}
                t0, t1 = int(a["t0"]), int(a["t1"])
                series = [{"t": hms(s), "s": s, "n": d.get(str(s), 0)}
                          for s in range(t0, t1 + 1)]
                return self._json({"event": ev, "series": series,
                                   "total": a["events"].get(ev, 0)})
            if p == "/api/discriminate":
                g = (q.get("group") or ["network"])[0]
                a = STATE["agg"]
                t0, t1 = a["t0"], a["t1"]
                b0 = float((q.get("b0") or [t0 + 5])[0])
                b1 = float((q.get("b1") or [t0 + 50])[0])
                i0 = float((q.get("i0") or [t0 + 60])[0])
                i1 = float((q.get("i1") or [t0 + 180])[0])
                return self._json(discriminate(g, b0, b1, i0, i1))
            if p == "/api/lines":
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
                return self._json({"current": RUN_ID,
                                   "runs": [dict(v, id=k) for k, v in RUNS.items()]})
            if p == "/api/select":
                rid = (q.get("run") or [""])[0]
                if rid in RUNS and rid != RUN_ID:
                    with LOCK:
                        load_state(False, rid)
                return self._json({"current": RUN_ID})
            if p == "/api/live/ready":
                return self._json(live_ready())
            if p == "/api/live/start":
                return self._json(live_start())
            if p == "/api/live/stop":
                return self._json(live_stop())
            if p == "/api/live/poll":
                return self._json(live_poll(int((q.get("since") or ["0"])[0])))
            if p == "/api/truth":
                return self._json(score_block())
            self.send_error(404)
        except Exception as e:                                          # noqa: BLE001
            self._json({"error": "%s: %s" % (type(e).__name__, e)})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--rebuild", action="store_true", help="discard the cached aggregate")
    a = ap.parse_args()
    load_state(a.rebuild)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    print()
    print("  StrataTrace demo   ->   http://127.0.0.1:%d" % a.port)
    print("  run %s   %s events over %.0f s   %d containers"
          % (RUN_ID, "{:,}".format(STATE["agg"]["rows"]),
             STATE["agg"]["t1"] - STATE["agg"]["t0"], len(STATE["agg"]["containers"])))
    print("  ctrl-c to stop")
    print()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
