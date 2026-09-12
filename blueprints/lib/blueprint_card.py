"""One analysis page per blueprint, drawn from the kernel trace.

WHAT THIS IS FOR
----------------
Two readers, both technical: someone reading the paper, and someone using the blueprint to
work an incident. Neither needs it to look nice. Both need numbers they can act on, so this
page is dense, plain, and has no decoration in it.

WHAT IS ON IT
-------------
Naser asked on 9 Sept for "a timeline, resources, waiting, or sometimes just a CPU usage".
Three of those four are drawn here, straight from the pack:

  A  THE RULER          every fault family on the one number this blueprint decides on, both
                        applications, with the cut. Needs 272 labelled runs - it is the one
                        panel that cannot be drawn from a single incident.
  B  RESOURCES          CPU per process, baseline against incident.
  C  WAITING FOR CPU    runqueue delay per service, baseline against incident.
  D  WAITING ON SOMETHING ELSE   blocking syscall p95 per process and call.
  E  GATES              every condition the rule tested, its value, its bar, its margin.
  F  THE FIELD          the other blueprints and the number that ruled each one out.

B, C and D are dumbbells: hollow dot = baseline, filled dot = incident, on a log axis. A log
axis because the ratios run from 1x to 5000x and a linear one would show a single spike and
eight flat lines.

THE TIMELINE IS NOT HERE, and that is a real gap rather than an oversight. The packs hold
baseline-vs-incident aggregates, not a series, so there is no time axis to draw. Getting one
means a new pass over the traces (G2, early detection). Faking it from two points would be
worse than leaving it out.

No libraries. Raw SVG from the standard library - the earlier attempts used matplotlib inside
a try/except, which is why ten blueprints declared a chart and none produced one.

    python3 blueprints/lib/blueprint_card.py --pack <pack.json> \
        --ruler blueprints/results/ruler.json --out card.svg
"""
import argparse
import io
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blueprint_decide as BD  # noqa: E402

W = 1100
PAD = 24
INK = "#111111"
MUTED = "#666666"
FAINT = "#cccccc"
ACCENT = "#0050b3"
WARN = "#b34700"
BAD = "#b3001b"
OK = "#1a7f37"
FONT = "DejaVu Sans,Segoe UI,Helvetica,Arial,sans-serif"
MONO = "DejaVu Sans Mono,Consolas,monospace"

# Which number each blueprint decides on, which family owns it, where the cut sits.
# The bars come from blueprint_decide rather than being retyped, so the drawn line cannot
# drift away from the line the code applies.
CARDS = {
    "host-cpu-saturation": dict(
        signal="host_util_incident", owns=["anomaly_cpu"], op=">=", bar=BD.SATURATED,
        rule="host_cpu_saturation"),
    "cpu-contention-co-tenant": dict(
        signal="thief_cores", owns=["noisy_neighbor"], op=">=", bar=BD.THIEF_CORES,
        ceiling=BD.BIG_THIEF, rule="cpu_contention_co_tenant"),
    "service-cpu-throttle": dict(
        signal="util_ratio", owns=["svc_cpu_cap"], op="<=", bar=BD.COLLAPSE_RATIO,
        rule="service_cpu_throttle"),
    "host-disk-saturation": dict(
        signal="iops_per_irq", owns=["anomaly_disk"], op=">", bar=BD.DISK_IOPS_PER_IRQ,
        rule="host_disk_saturation"),
    "service-memory-cap": dict(
        signal="hardirq_x", owns=["svc_mem_cap"], op=">=", bar=BD.IRQ_X,
        rule="service_memory_cap"),
    "network-path-degradation": dict(
        signal="worst_retrans_pct", owns=["anomaly_net", "svc_net"], op=">=",
        bar=BD.RETRANS_FIRE_PCT, rule="network_path_degradation"),
    "db-latency-dependency-wait": dict(
        signal="socket_block_x", owns=["slow_db"], op=">=", bar=BD.BLOCK_X,
        rule="datastore_wait"),
    # Measured and written up, but no rule implements them yet. The card says so rather than
    # drawing a decision the engine cannot make.
    "fork-storm": dict(
        signal="fork_newcomer_per_s", owns=["fork_storm"], op=">", bar=26.34, rule=None),
    "data-exfiltration": dict(
        signal="tx_newcomer_bytes_per_s", owns=["data_exfiltration"], op=">", bar=3.64e6,
        rule=None),
    "fd-exhaustion": dict(
        signal="emfile_per_s", owns=["fd_exhaustion"], op="band", bar=(0.13, 9.28), rule=None),
}

RULE_TO_CARD = {v["rule"]: k for k, v in CARDS.items() if v["rule"]}


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt(v, unit=""):
    if v is None:
        return "n/a"
    if unit == "bytes/s":
        for div, suf in ((1e9, "G"), (1e6, "M"), (1e3, "k")):
            if abs(v) >= div:
                return "%.3g%s" % (v / div, suf)
        return "%.0f" % v
    if v == 0:
        return "0"
    if abs(v) >= 1e6:
        return "%.3g" % v
    if abs(v) >= 1000:
        return "%.0f" % v
    if abs(v) >= 10:
        return "%.1f" % v
    if abs(v) >= 1:
        return "%.2f" % v
    return "%.3g" % v


def clip(s, n):
    s = str(s or "")
    if len(s) <= n:
        return s
    cut = s[:n]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > n * 0.6 else cut).rstrip(" ,;-") + "..."


class Svg(object):
    def __init__(self):
        self.parts = []

    def add(self, s):
        self.parts.append(s)

    def rect(self, x, y, w, h, fill, stroke="none", sw=1, op=1.0):
        self.add('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" stroke="%s" '
                 'stroke-width="%s" opacity="%s"/>'
                 % (x, y, max(w, 0), max(h, 0), fill, stroke, sw, op))

    def line(self, x1, y1, x2, y2, stroke, sw=1, dash=None, op=1.0):
        d = ' stroke-dasharray="%s"' % dash if dash else ""
        self.add('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
                 'stroke-width="%s"%s opacity="%s"/>' % (x1, y1, x2, y2, stroke, sw, d, op))

    def text(self, x, y, s, size=10, fill=INK, anchor="start", weight="normal",
             font=FONT, op=1.0):
        self.add('<text x="%.1f" y="%.1f" font-family="%s" font-size="%s" fill="%s" '
                 'text-anchor="%s" font-weight="%s" opacity="%s">%s</text>'
                 % (x, y, font, size, fill, anchor, weight, op, esc(s)))

    def circle(self, cx, cy, r, fill, stroke="none", sw=1, op=1.0):
        self.add('<circle cx="%.2f" cy="%.2f" r="%.2f" fill="%s" stroke="%s" '
                 'stroke-width="%s" opacity="%s"/>' % (cx, cy, r, fill, stroke, sw, op))

    def poly(self, pts, fill, op=1.0):
        self.add('<polygon points="%s" fill="%s" opacity="%s"/>'
                 % (" ".join("%.1f,%.1f" % xy for xy in pts), fill, op))


class Axis(object):
    """Value to x position. Zero gets its own slot at the left, because many families measure
    EXACTLY zero on a signal and that fact is evidence, not a gap to hide."""

    def __init__(self, values, x0, x1, force_log=None):
        self.x0, self.x1 = x0, x1
        vals = [v for v in values if v is not None]
        pos = [v for v in vals if v > 0] or [1.0]
        self.has_zero = any(v == 0 for v in vals)
        lo, hi = min(pos), max(pos)
        self.log = force_log if force_log is not None else ((hi / lo) > 50 if lo > 0 else True)
        if self.log:
            self.lo, self.hi = lo / 2.0, hi * 2.0
        else:
            span = (hi - lo) or abs(hi) or 1.0
            self.lo, self.hi = lo - span * 0.10, hi + span * 0.10
            if min(vals or [0]) >= 0 and self.lo < 0:
                self.lo = 0.0
        self.zw = 34 if self.has_zero else 0
        self.px0 = x0 + self.zw

    def x(self, v):
        if v is None:
            return None
        if v <= 0:
            return self.x0 + self.zw / 2.0 if self.has_zero else self.px0
        if self.log:
            f = ((math.log10(v) - math.log10(self.lo))
                 / (math.log10(self.hi) - math.log10(self.lo)))
        else:
            f = (v - self.lo) / (self.hi - self.lo)
        return self.px0 + max(0.0, min(1.0, f)) * (self.x1 - self.px0)

    def ticks(self):
        out = []
        if self.log:
            e = int(math.floor(math.log10(self.lo)))
            while 10 ** e <= self.hi:
                for m in (1, 3):
                    v = m * 10 ** e
                    if self.lo <= v <= self.hi:
                        out.append(v)
                e += 1
        else:
            span = self.hi - self.lo
            step = 10 ** math.floor(math.log10(span / 4.0)) if span > 0 else 1.0
            for mult in (1, 2, 2.5, 5, 10):
                if span / (step * mult) <= 6:
                    step *= mult
                    break
            v = math.ceil(self.lo / step) * step
            while v <= self.hi:
                out.append(round(v, 10))
                v += step
        return out


def panel(s, y, letter, title, note=""):
    s.line(PAD, y, W - PAD, y, FAINT, 1)
    s.text(PAD, y + 14, letter, 9.5, MUTED, weight="bold")
    s.text(PAD + 14, y + 14, title, 10.5, INK, weight="bold")
    if note:
        s.text(W - PAD, y + 14, note, 9, MUTED, anchor="end")
    return y + 22


# --------------------------------------------------------------------------------- ruler
def draw_ruler(s, y, cfg, ruler, this_run):
    sig = ruler["signals"].get(cfg["signal"])
    lines = []
    if not sig or not sig["points"]:
        s.text(PAD, y + 12, "no measurement of this signal in the ruler file", 10, WARN)
        return y + 24, lines

    pts, unit, owns = sig["points"], sig["unit"], set(cfg["owns"])
    apps = sorted(set(p["app"] for p in pts))
    band, bar, ceil = cfg["op"] == "band", cfg["bar"], cfg.get("ceiling")

    y = panel(s, y, "A", "DECIDING SIGNAL, EVERY RUN WE HAVE  -  " + sig["label"],
              "%d runs · %d families · %d applications"
              % (len(pts), len(set(p["family"] for p in pts)), len(apps)))

    ax = Axis([p["v"] for p in pts] + (list(bar) if band else [bar]), PAD + 74, W - PAD - 8)
    lane_h = 30
    top = y + 16

    if band:
        fires = lambda v: bar[0] <= v <= bar[1]                          # noqa: E731
    elif cfg["op"] in (">=", ">"):
        fires = lambda v: v >= bar and (ceil is None or v < ceil)        # noqa: E731
    else:
        fires = lambda v: v <= bar                                       # noqa: E731

    near = None
    if not band:
        side = ([p for p in pts if p["family"] not in owns and p["v"] < bar]
                if cfg["op"] in (">=", ">") else
                [p for p in pts if p["family"] not in owns and p["v"] > bar])
        if side:
            near = (max if cfg["op"] in (">=", ">") else min)(side, key=lambda p: p["v"])

    for i, app in enumerate(apps):
        ly = top + i * lane_h
        s.rect(ax.px0, ly, W - PAD - 8 - ax.px0, lane_h - 5, "#f4f4f4")
        if ax.has_zero:
            s.rect(ax.x0, ly, ax.zw - 4, lane_h - 5, "#f4f4f4")
        s.text(PAD + 68, ly + lane_h / 2.0, app, 9, MUTED, anchor="end")
        rows = sorted([p for p in pts if p["app"] == app],
                      key=lambda p: (p["family"] not in owns, p["v"]))
        seen = {}
        for p in rows:
            cx = ax.x(p["v"])
            b = int(cx / 5.0)
            seen[b] = seen.get(b, 0) + 1
            cy = ly + 6 + ((seen[b] - 1) % 4) * 4.6
            if p["family"] in owns:
                s.circle(cx, cy, 3.4, ACCENT, stroke="#ffffff", sw=0.8)
            else:
                s.circle(cx, cy, 2.2, "#555555", op=0.40)
    bottom = top + lane_h * len(apps)

    def cut(v, lab):
        cx = ax.x(v)
        s.line(cx, top - 10, cx, bottom, BAD, 1.3, dash="4,3")
        s.text(cx, bottom + 11, lab, 9, BAD, anchor="middle", weight="bold")

    if band:
        cut(bar[0], "cut " + fmt(bar[0], unit))
        cut(bar[1], "cut " + fmt(bar[1], unit))
    else:
        cut(bar, "%s %s" % (cfg["op"], fmt(bar, unit)))
    if ceil:
        cut(ceil, "< " + fmt(ceil, unit))

    for v in ax.ticks():
        if not (ax.has_zero and v == 0):
            s.text(ax.x(v), bottom + 22, fmt(v, unit), 8.5, MUTED, anchor="middle")
    if ax.has_zero:
        s.text(ax.x0 + ax.zw / 2.0 - 2, bottom + 22, "0", 8.5, MUTED, anchor="middle")
    s.text(W - PAD - 8, bottom + 33, unit + (", log scale" if ax.log else ""), 8.5, MUTED,
           anchor="end")

    mine = [p for p in pts if p["run"] == this_run]
    if mine:
        v = mine[0]["v"]
        mx = ax.x(v)
        s.line(mx, top - 14, mx, bottom, ACCENT, 1.2)
        s.poly([(mx - 4, top - 18), (mx + 4, top - 18), (mx, top - 11)], ACCENT)
        lab = "this run " + fmt(v, unit)
        if mx > W - 170:
            s.text(mx - 7, top - 12, lab, 9.5, ACCENT, weight="bold", anchor="end")
        else:
            s.text(mx + 7, top - 12, lab, 9.5, ACCENT, weight="bold")
        lines.append("This run measured %s on %s. Cut at %s."
                     % (fmt(v, unit), sig["label"],
                        "%s-%s" % (fmt(bar[0]), fmt(bar[1])) if band else fmt(bar, unit)))

    # margin to the nearest fault that would break the cut - the number that matters most
    if near is not None:
        try:
            margin = (bar / near["v"]) if cfg["op"] in (">=", ">") else (near["v"] / bar)
        except ZeroDivisionError:
            margin = None
        mt = ("nearest other fault: %s / %s at %s"
              % (near["family"], near["app"], fmt(near["v"], unit)))
        if margin:
            mt += "   margin %.2fx" % margin
        s.text(PAD, bottom + 33, mt, 9, WARN if (margin and margin < 1.25) else MUTED)
        lines.append(mt)

    wrong = [p for p in pts if fires(p["v"]) != (p["family"] in owns)]
    a = ("this signal alone separates all %d" % len(pts) if not wrong
         else "this signal alone: %d of %d runs on the wrong side" % (len(wrong), len(pts)))
    s.text(W - PAD - 8, bottom + 45, a, 9.5, OK if not wrong else WARN, anchor="end")
    lines.append(a)

    vs = ruler.get("verdicts") or []
    if vs and cfg.get("rule"):
        bid = RULE_TO_CARD[cfg["rule"]]
        sel = "datastore-wait" if bid == "db-latency-dependency-wait" else bid
        bad = [v for v in vs if (v.get("selected") == sel) != (v["family"] in owns)]
        f = "every gate together: %d of %d correct" % (len(vs) - len(bad), len(vs))
        s.text(W - PAD - 8, bottom + 57, f, 9.5, INK, anchor="end", weight="bold")
        lines.append(f)
        return bottom + 66, lines
    return bottom + 54, lines


# ----------------------------------------------------------------------------- dumbbells
def draw_pairs(s, y, letter, title, unit, rows, limit=7):
    """Baseline -> incident, one row per entity, on a shared log axis.

    A dumbbell rather than paired bars because these ratios run from 1x to 5000x. Paired bars
    on a linear axis would show one spike and six flat lines; on a log axis a bar has no
    meaningful origin. Two dots and the distance between them survive both problems.
    """
    lines = []
    rows = [r for r in rows if r[1] is not None and r[2] is not None]
    if not rows:
        y = panel(s, y, letter, title)
        s.text(PAD, y + 10, "not in this pack", 9, MUTED)
        return y + 20, lines

    # Sort by ABSOLUTE change, not by ratio. Ratio puts a process that went from 0.0003 to
    # 0.03 cores at the top - a 100x rise that means nothing - and pushes the service that
    # actually moved to the bottom. What an analyst needs first is what moved most in real
    # units; the ratio is still shown on every row.
    rows.sort(key=lambda r: -abs(r[2] - r[1]))
    rows = rows[:limit]
    y = panel(s, y, letter, title, unit)

    ax = Axis([r[1] for r in rows] + [r[2] for r in rows], PAD + 210, W - PAD - 56)
    rh = 13
    top = y + 6
    for i, (name, b, inc) in enumerate(rows):
        ry = top + i * rh + 6
        s.text(PAD + 204, ry + 3, clip(name, 34), 9, INK, anchor="end", font=MONO)
        xb, xi = ax.x(b), ax.x(inc)
        rat = (inc / b) if b else None
        up = xi >= xb
        col = BAD if (rat and rat >= 2.0) else (ACCENT if up else MUTED)
        s.line(xb, ry + 3, xi, ry + 3, col, 1.2, op=0.55)
        s.circle(xb, ry + 3, 2.8, "#ffffff", stroke=MUTED, sw=1.2)
        s.circle(xi, ry + 3, 3.2, col)
        # A zero baseline is not a missing ratio - it means this entity was not there before,
        # which is usually the most interesting row on the panel.
        rs = "new" if rat is None else ("%.0fx" % rat if rat >= 100 else "%.2fx" % rat)
        s.text(W - PAD, ry + 6, rs, 9, col if (rat is None or rat >= 2.0) else MUTED,
               anchor="end", font=MONO)
        lines.append("%s: %s -> %s (%s)" % (name, fmt(b), fmt(inc), rs))
    bottom = top + len(rows) * rh + 8
    for v in ax.ticks():
        if not (ax.has_zero and v == 0):
            s.text(ax.x(v), bottom + 8, fmt(v), 8, MUTED, anchor="middle")
    if ax.has_zero:
        s.text(ax.x0 + ax.zw / 2.0 - 2, bottom + 8, "0", 8, MUTED, anchor="middle")
    s.circle(PAD + 6, bottom + 5, 2.8, "#ffffff", stroke=MUTED, sw=1.2)
    s.text(PAD + 13, bottom + 8, "baseline", 8, MUTED)
    s.circle(PAD + 62, bottom + 5, 3.2, INK)
    s.text(PAD + 69, bottom + 8, "during the fault", 8, MUTED)
    if ax.log:
        s.text(W - PAD, bottom + 8, "log scale", 8, MUTED, anchor="end")
    return bottom + 16, lines


def series_for(pack):
    g = (pack.get("oncpu") or {}).get("top_gainers") or []
    rq = (pack.get("runqueue_delay") or {}).get("top_by_inflation") or []
    bs = (pack.get("blocking_syscall") or {}).get("top_by_inflation") or []
    return [
        ("B", "RESOURCES  -  CPU held by each process", "cores",
         [(r.get("comm"), r.get("cores_baseline"), r.get("cores_incident")) for r in g]),
        ("C", "WAITING FOR CPU  -  runqueue delay per service", "p95 milliseconds",
         [(r.get("service"), r.get("p95_baseline_ms"), r.get("p95_incident_ms")) for r in rq]),
        ("D", "WAITING ON SOMETHING ELSE  -  time blocked in a syscall", "p95 milliseconds",
         [(r.get("comm_syscall"), r.get("p95_baseline_ms"), r.get("p95_incident_ms"))
          for r in bs]),
    ]


# --------------------------------------------------------------------------------- gates
def draw_gates(s, y, gates, note):
    y = panel(s, y, "E", "GATES  -  every condition the rule tested")
    lines = []
    if not gates:
        s.text(PAD, y + 10, note or "no rule implements this blueprint yet", 9.5, WARN)
        return y + 20, lines
    rh = 15
    s.text(PAD, y + 8, "condition", 8, MUTED)
    s.text(PAD + 300, y + 8, "measured", 8, MUTED, anchor="end")
    s.text(PAD + 316, y + 8, "needs", 8, MUTED)
    s.text(PAD + 560, y + 8, "margin", 8, MUTED, anchor="end")
    s.text(PAD + 600, y + 8, "result", 8, MUTED)
    for i, g in enumerate(gates):
        ry = y + 18 + i * rh
        ok, veto = g["pass"], g.get("kind") == "veto"
        col = OK if ok else BAD
        s.text(PAD, ry, ("veto: " if veto else "") + clip(g["name"], 46), 9.5, INK)
        if g["value"] is None:
            s.text(PAD + 300, ry, clip(g.get("detail"), 26), 9.5, INK, anchor="end", font=MONO)
            s.text(PAD + 316, ry, "no number to compare", 9, MUTED)
        else:
            s.text(PAD + 300, ry, fmt(g["value"], g["unit"]), 9.5, INK, anchor="end",
                   font=MONO)
            s.text(PAD + 316, ry, "%s %s %s" % (g["op"], fmt(g["bar"], g["unit"]), g["unit"]),
                   9, MUTED)
            try:
                room = (g["value"] / g["bar"]) if g["op"] in (">=", ">") \
                    else (g["bar"] / g["value"])
                if room and 0 < room < 9999:
                    s.text(PAD + 560, ry, "%.2fx" % room, 9, WARN if room < 1.3 else MUTED,
                           anchor="end", font=MONO)
            except (TypeError, ZeroDivisionError):
                pass
        s.text(PAD + 600, ry, "PASS" if ok else "FAIL", 9.5, col, weight="bold")
        lines.append("%s: %s %s" % (g["name"], "pass" if ok else "FAIL",
                                    ("(%s needs %s %s)" % (fmt(g["value"]), g["op"],
                                                           fmt(g["bar"])))
                                    if g["value"] is not None else (g.get("detail") or "")))
    return y + 22 + len(gates) * rh, lines


# --------------------------------------------------------------------------------- field
def draw_field(s, y, verdict, selected):
    y = panel(s, y, "F", "OTHER BLUEPRINTS CONSIDERED  -  and the number that ruled each out")
    rows, lines = [], []
    for rule_key, card_id in RULE_TO_CARD.items():
        r = verdict.get(rule_key)
        if isinstance(r, dict):
            rows.append((card_id, bool(r.get("fires")), r.get("why", "")))
    rows.sort(key=lambda t: (not t[1], t[0]))
    rh = 14
    for i, (name, fired, why) in enumerate(rows):
        ry = y + 12 + i * rh
        s.text(PAD, ry, ">" if fired else " ", 9.5, OK, weight="bold")
        s.text(PAD + 10, ry, name, 9.5, INK if fired else MUTED,
               weight="bold" if name == selected else "normal")
        s.text(PAD + 220, ry, clip(why, 118), 9, MUTED)
        lines.append("%s %s - %s" % ("FIRED" if fired else "no   ", name, clip(why, 150)))
    return y + 18 + len(rows) * rh, lines


# ---------------------------------------------------------------------------------- card
def build(pack, ruler, blueprint_id=None, problems=""):
    verdict = BD.decide(pack)
    selected = verdict.get("selected")
    if selected == "datastore-wait":
        selected = "db-latency-dependency-wait"
    bid = blueprint_id or selected
    if bid not in CARDS:
        bid = selected if selected in CARDS else None

    bp = None
    if problems and bid:
        p = os.path.join(problems, bid, "blueprint.json")
        if os.path.exists(p):
            bp = json.load(io.open(p, encoding="utf-8"))

    s = Svg()
    cfg = CARDS.get(bid)
    fired = bool(bid and selected == bid)

    s.text(PAD, 20, (bid or "no blueprint matched").upper(), 13, INK, weight="bold")
    s.text(PAD + 300, 20, "FIRES" if fired else "DID NOT FIRE", 11,
           OK if fired else MUTED, weight="bold")
    if fired:
        s.text(PAD + 380, 20, "confidence %.2f" % (verdict.get("confidence") or 0.0), 9.5,
               MUTED)
    s.text(W - PAD, 20, "%s  ·  %s" % (pack.get("run_id", "?"), pack.get("app", "?")), 9.5,
           MUTED, anchor="end", font=MONO)
    rc = ((bp or {}).get("decision") or {}).get("root_cause_is") or ""
    svc = verdict.get("root_cause_service")
    s.text(PAD, 34, clip("root cause: " + (rc or "see the verdict line"), 108), 9.5, INK)
    s.text(W - PAD, 34, "names: %s" % (svc or "not resolvable from the kernel trace alone"),
           9, MUTED, anchor="end")

    desc = ["%s on run %s (%s): %s."
            % (bid, pack.get("run_id"), pack.get("app"),
               "fires" if fired else "did not fire")]
    y = 44
    if cfg:
        y, l = draw_ruler(s, y, cfg, ruler, pack.get("run_id"))
        desc += l
    for letter, title, unit, rows in series_for(pack):
        y, l = draw_pairs(s, y, letter, title, unit, rows)
        desc += l

    rule_res = verdict.get(cfg["rule"]) if (cfg and cfg["rule"]) else None
    note = None
    if cfg and not cfg["rule"]:
        note = ("this blueprint's rule is written and measured, but the rule engine does not "
                "implement it yet - there are no gates to show")
    elif rule_res and not (rule_res.get("gates") or []):
        note = rule_res.get("why")
    y, l = draw_gates(s, y, (rule_res or {}).get("gates") or [], note)
    desc += l
    y, l = draw_field(s, y, verdict, bid)
    desc += l

    s.line(PAD, y, W - PAD, y, FAINT, 1)
    s.text(PAD, y + 13, "kernel trace only · ruler from %d runs · no time axis yet: the packs "
                        "hold baseline-vs-incident totals, not a series"
           % ruler.get("n_packs", 0), 8.5, MUTED)
    if (rule_res or {}).get("why"):
        s.text(PAD, y + 26, clip("verdict: " + rule_res["why"], 150), 9, INK)
    H = y + 34

    out = ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
           'viewBox="0 0 %d %d" font-family="%s">' % (W, H, W, H, FONT))
    out += "<title>%s</title>" % esc("blueprint card: %s / %s" % (bid, pack.get("run_id")))
    out += "<desc>%s</desc>" % esc(chr(10).join(desc))
    out += '<rect width="%d" height="%d" fill="#ffffff"/>' % (W, H)
    return out + "".join(s.parts) + "</svg>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True)
    ap.add_argument("--ruler", required=True)
    ap.add_argument("--blueprint", default="")
    ap.add_argument("--problems", default="")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    pack = json.load(io.open(a.pack, encoding="utf-8"))
    ruler = json.load(io.open(a.ruler, encoding="utf-8"))
    svg = build(pack, ruler, a.blueprint or None, a.problems)
    with io.open(a.out, "w", encoding="utf-8", newline=chr(10)) as fh:
        fh.write(svg)
    print("wrote %s  (%d bytes)" % (a.out, len(svg)))


if __name__ == "__main__":
    main()
