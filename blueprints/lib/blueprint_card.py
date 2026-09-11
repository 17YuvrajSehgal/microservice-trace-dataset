"""Draw one picture that shows WHY a blueprint decided what it decided.

The 9 Sept meeting asked for a picture per problem, made from the trace, not from Trace
Compass. Every blueprint already declared an `.svg` output and none of them drew one, because
the two attempts used matplotlib inside a try/except and it silently skipped. This draws raw
SVG from the standard library, so it cannot skip.

WHAT MAKES THIS CARD DIFFERENT FROM A METRICS CHART
---------------------------------------------------
A dashboard shows the number that moved. That is detection. The meeting was explicit that
detection is not root cause: "just saying the system is under contention is not known".

So the card shows the DECISION instead, in three bands:

  1. THE RULER   Every fault family we have, on the one axis this blueprint decides on, with
                 the cut drawn. You can see the gap the blueprint relies on, which family came
                 closest to breaking it, and whether the cut lands the same way on both
                 applications. Only possible because we have 273 labelled runs over 27
                 families - nobody can draw this from one incident.

  2. THE GATES   Every condition the rule tested, with the measured number, the bar, and how
                 much room it had. A rule that passed by a hair and a rule that passed by 8x
                 both read "fired"; here they look different.

  3. THE FIELD   The other blueprints and the single number that ruled each one out. Ruling
                 out is most of what root-cause work actually is.

The SVG also carries a plain-text <desc> summarising all three bands, so an agent reading the
file gets the same story as a person looking at it.

    python3 blueprints/lib/blueprint_card.py --pack <pack.json> --ruler blueprints/results/ruler.json --out card.svg
"""
import argparse
import io
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blueprint_decide as BD  # noqa: E402

W = 1060
PAD = 28
INK = "#1b1f24"
MUTED = "#6a737d"
FAINT = "#d0d7de"
PANEL = "#f6f8fa"
ACCENT = "#0b6bcb"
FIRE = "#1a7f37"
FAIL = "#cf222e"
VETO = "#9a6700"
FONT = "DejaVu Sans,Segoe UI,Helvetica,Arial,sans-serif"
MONO = "DejaVu Sans Mono,Consolas,monospace"

# Which number each blueprint decides on, which family owns it, and where the cut sits.
# `bar` is a single value with a direction, or a (low, high) band. These are the SAME
# constants the rules use, imported rather than retyped, so the drawn line cannot drift
# away from the line the code actually applies.
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
    # These three are measured and written up, but no rule implements them yet. The card says
    # so rather than drawing a decision the engine cannot make.
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
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def fmt(v, unit=""):
    """Short, readable numbers. Bytes get their own treatment or the axis is unreadable."""
    if v is None:
        return "n/a"
    if unit == "bytes/s":
        for div, suf in ((1e9, " GB/s"), (1e6, " MB/s"), (1e3, " kB/s")):
            if abs(v) >= div:
                return "%.3g%s" % (v / div, suf)
        return "%.0f B/s" % v
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


def wrap(s, n, lines=2):
    """Break a gate name over at most `lines` lines so it stays inside its box."""
    words, out, cur = str(s).split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > n:
            out.append(cur)
            cur = w
            if len(out) == lines:
                break
        else:
            cur = (cur + " " + w).strip()
    if cur and len(out) < lines:
        out.append(cur)
    return out or [""]


class Svg(object):
    def __init__(self):
        self.parts = []

    def add(self, s):
        self.parts.append(s)

    def rect(self, x, y, w, h, fill, rx=0, stroke="none", sw=1, op=1.0):
        self.add('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="%d" fill="%s" '
                 'stroke="%s" stroke-width="%s" opacity="%s"/>'
                 % (x, y, max(w, 0), max(h, 0), rx, fill, stroke, sw, op))

    def line(self, x1, y1, x2, y2, stroke, sw=1, dash=None, op=1.0):
        d = ' stroke-dasharray="%s"' % dash if dash else ""
        self.add('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
                 'stroke-width="%s"%s opacity="%s"/>' % (x1, y1, x2, y2, stroke, sw, d, op))

    def text(self, x, y, s, size=12, fill=INK, anchor="start", weight="normal",
             font=FONT, op=1.0, spacing=None):
        ls = ' letter-spacing="%s"' % spacing if spacing else ""
        self.add('<text x="%.1f" y="%.1f" font-family="%s" font-size="%s" fill="%s" '
                 'text-anchor="%s" font-weight="%s" opacity="%s"%s>%s</text>'
                 % (x, y, font, size, fill, anchor, weight, op, ls, esc(s)))

    def circle(self, cx, cy, r, fill, stroke="none", sw=1, op=1.0):
        self.add('<circle cx="%.2f" cy="%.2f" r="%.2f" fill="%s" stroke="%s" '
                 'stroke-width="%s" opacity="%s"/>' % (cx, cy, r, fill, stroke, sw, op))

    def poly(self, pts, fill, op=1.0):
        p = " ".join("%.1f,%.1f" % xy for xy in pts)
        self.add('<polygon points="%s" fill="%s" opacity="%s"/>' % (p, fill, op))


# ----------------------------------------------------------------------------- the ruler
class Axis(object):
    """Maps a measured value to an x position.

    Two things make this awkward and both are real, so both are handled rather than hidden:
    many families measure EXACTLY zero on a signal (that is the point - it is why absence is
    evidence), and the spans reach six orders of magnitude. So zero gets its own lane at the
    left, clearly separated, and everything else is log-scaled when the span demands it.
    """

    def __init__(self, values, x0, x1):
        self.x0, self.x1 = x0, x1
        pos = [v for v in values if v is not None and v > 0]
        self.has_zero = any(v == 0 for v in values if v is not None)
        if not pos:
            pos = [1.0]
        lo, hi = min(pos), max(pos)
        self.log = (hi / lo) > 50 if lo > 0 else True
        if self.log:
            self.lo, self.hi = lo / 2.0, hi * 2.0
        else:
            span = (hi - lo) or abs(hi) or 1.0
            self.lo, self.hi = lo - span * 0.12, hi + span * 0.12
            if min(values or [0]) >= 0 and self.lo < 0:
                self.lo = 0.0                      # a count never goes below zero
        self.zw = 44 if self.has_zero else 0        # width of the zero lane
        self.px0 = x0 + self.zw

    def x(self, v):
        if v is None:
            return None
        if v <= 0:
            return self.x0 + self.zw / 2.0 if self.has_zero else self.px0
        if self.log:
            f = (math.log10(v) - math.log10(self.lo)) / (math.log10(self.hi) - math.log10(self.lo))
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


def draw_ruler(s, y, cfg, ruler, this_run, app_of_run):
    """Band 1. Every family on one axis, with the cut, the gap, and the closest miss."""
    sig = ruler["signals"].get(cfg["signal"])
    lines = []
    if not sig or not sig["points"]:
        s.text(PAD, y + 18, "No measurement of this signal in the ruler file.", 12, MUTED)
        return y + 34, lines

    pts = sig["points"]
    unit = sig["unit"]
    owns = set(cfg["owns"])
    apps = sorted(set(p["app"] for p in pts))
    band = cfg["op"] == "band"
    bar = cfg["bar"]

    s.text(PAD, y + 14, "1 · THE RULER", 11, MUTED, weight="bold", spacing="1.4")
    s.text(PAD + 118, y + 14, "where every fault we have measured sits on this one number",
           11, MUTED)
    s.text(PAD, y + 38, sig["label"], 15, INK, weight="bold")
    s.text(PAD, y + 56, "%d runs · %d fault families · %d applications"
           % (len(pts), len(set(p["family"] for p in pts)), len(apps)), 11, MUTED)

    ax = Axis([p["v"] for p in pts] + ([bar[0], bar[1]] if band else [bar]),
              PAD + 96, W - PAD - 16)
    lane_h = 42
    top = y + 74

    # the margin: how much room the cut has before a negative run crosses it
    posv = [p["v"] for p in pts if p["family"] in owns]
    negv = [p["v"] for p in pts if p["family"] not in owns]
    # The ceiling is part of the cut wherever a rule has one (a co-tenant is bounded; a
    # process taking six cores is host saturation). Leaving it out of this test would let the
    # card claim a clean separation the rule does not actually make.
    ceil = cfg.get("ceiling")
    if band:
        fires = lambda v: bar[0] <= v <= bar[1]                          # noqa: E731
    elif cfg["op"] in (">=", ">"):
        fires = lambda v: v >= bar and (ceil is None or v < ceil)        # noqa: E731
    else:
        fires = lambda v: v <= bar                                       # noqa: E731

    # closest negative to the cut, on the side that would break the rule
    near = None
    if negv and not band:
        if cfg["op"] in (">=", ">"):
            below = [p for p in pts if p["family"] not in owns and p["v"] < bar]
            near = max(below, key=lambda p: p["v"]) if below else None
        else:
            above = [p for p in pts if p["family"] not in owns and p["v"] > bar]
            near = min(above, key=lambda p: p["v"]) if above else None

    # the gap corridor, drawn only when it is real
    if posv and near is not None:
        lo_p, hi_n = min(posv), near["v"]
        if cfg["op"] in (">=", ">") and lo_p > hi_n:
            gx0, gx1, ratio = ax.x(hi_n), ax.x(lo_p), lo_p / hi_n if hi_n else None
        elif cfg["op"] in ("<=", "<") and max(posv) < hi_n:
            gx0, gx1, ratio = ax.x(max(posv)), ax.x(hi_n), hi_n / max(posv) if posv else None
        else:
            gx0 = None
        if gx0 is not None:
            s.rect(gx0, top, gx1 - gx0, lane_h * len(apps) + 6, "#1a7f37", op=0.07)
            if ratio and ratio > 1.05:
                s.text((gx0 + gx1) / 2.0, top - 6, "%.3gx gap" % ratio, 10, FIRE,
                       anchor="middle", weight="bold")
                lines.append("The gap between the nearest other fault and this one is %.3gx."
                             % ratio)

    # one lane per application - this is where "does the cut transfer?" is answered
    for i, app in enumerate(apps):
        ly = top + i * lane_h
        s.rect(PAD + 96, ly, W - PAD - 16 - (PAD + 96), lane_h - 6, PANEL, rx=4)
        s.text(PAD + 88, ly + lane_h / 2.0, app, 11, MUTED, anchor="end")
        if ax.has_zero:
            s.line(ax.x0 + ax.zw, ly, ax.x0 + ax.zw, ly + lane_h - 6, FAINT, 1)
        rows = [p for p in pts if p["app"] == app]
        for j, p in enumerate(rows):
            own = p["family"] in owns
            cx = ax.x(p["v"])
            cy = ly + 8 + ((j * 7) % (lane_h - 22))            # jitter so runs do not hide
            if own:
                s.circle(cx, cy, 4.6, ACCENT, stroke="#ffffff", sw=1.2, op=0.95)
            else:
                s.circle(cx, cy, 2.7, "#57606a", op=0.42)

    bottom = top + lane_h * len(apps)

    # the cut
    def cutline(v, label):
        cx = ax.x(v)
        s.line(cx, top - 14, cx, bottom + 4, FAIL, 1.6, dash="5,3")
        s.text(cx, bottom + 17, label, 10, FAIL, anchor="middle", weight="bold")

    if band:
        cutline(bar[0], "cut %s" % fmt(bar[0], unit))
        cutline(bar[1], "cut %s" % fmt(bar[1], unit))
        s.rect(ax.x(bar[0]), top, ax.x(bar[1]) - ax.x(bar[0]), bottom - top, FAIL, op=0.05)
    else:
        cutline(bar, "%s %s" % (cfg["op"], fmt(bar, unit)))
    if cfg.get("ceiling"):
        cutline(cfg["ceiling"], "< %s" % fmt(cfg["ceiling"], unit))

    # axis ticks
    for v in ax.ticks():
        s.text(ax.x(v), bottom + 30, fmt(v, unit), 9, MUTED, anchor="middle")
    if ax.has_zero:
        s.text(ax.x0 + ax.zw / 2.0, bottom + 30, "0", 9, MUTED, anchor="middle")
        s.text(ax.x0 + ax.zw / 2.0, top - 6, "exactly 0", 8, MUTED, anchor="middle")
    s.text(W - PAD - 16, bottom + 44, unit + ("  (log scale)" if ax.log else ""), 9, MUTED,
           anchor="end")

    # this run
    mine = [p for p in pts if p["run"] == this_run]
    if mine:
        v = mine[0]["v"]
        mx = ax.x(v)
        s.line(mx, top - 26, mx, bottom + 4, ACCENT, 1.4, op=0.75)
        s.poly([(mx - 5, top - 30), (mx + 5, top - 30), (mx, top - 21)], ACCENT)
        s.text(mx + 9, top - 22, "this run  %s" % fmt(v, unit), 10.5, ACCENT, weight="bold")
        lines.append("This run measured %s %s on \"%s\"; the cut is at %s."
                     % (fmt(v, unit), unit, sig["label"],
                        fmt(bar[0], unit) + "-" + fmt(bar[1], unit) if band else fmt(bar, unit)))

    if near is not None:
        s.text(PAD, bottom + 44,
               "closest other fault to the cut:  %s on %s at %s"
               % (near["family"], near["app"], fmt(near["v"], unit)), 10, MUTED)
        lines.append("The fault that comes closest to breaking this cut is %s on %s at %s."
                     % (near["family"], near["app"], fmt(near["v"], unit)))

    # honesty line: does the cut actually hold over everything we measured?
    wrong = [p for p in pts if fires(p["v"]) != (p["family"] in owns)]
    msg = ("this cut separates all %d runs" % len(pts) if not wrong
           else "%d of %d runs fall on the wrong side of this cut" % (len(wrong), len(pts)))
    s.text(W - PAD - 16, bottom + 56, msg, 10, FIRE if not wrong else VETO, anchor="end",
           weight="bold")
    lines.append(msg.capitalize() + ".")
    return bottom + 68, lines


# ----------------------------------------------------------------------------- the gates
def draw_gates(s, y, gates, note):
    s.text(PAD, y + 14, "2 · THE GATES", 11, MUTED, weight="bold", spacing="1.4")
    s.text(PAD + 118, y + 14, "every test the rule had to pass, and by how much", 11, MUTED)
    lines = []
    if not gates:
        s.rect(PAD, y + 26, W - 2 * PAD, 40, PANEL, rx=6)
        s.text(PAD + 14, y + 51, note or "no rule implements this blueprint yet", 12, VETO)
        return y + 80, [note] if note else []

    n = len(gates)
    gap = 11
    bw = (W - 2 * PAD - gap * (n - 1)) / float(n)
    chars = max(12, int(bw / 5.2))
    top = y + 30
    h = 96
    for i, g in enumerate(gates):
        x = PAD + i * (bw + gap)
        ok, veto = g["pass"], g.get("kind") == "veto"
        col = (VETO if veto else FIRE) if ok else FAIL
        s.rect(x, top, bw, h, "#ffffff", rx=6, stroke=col, sw=1.5)
        s.rect(x, top, bw, 3.5, col)
        s.rect(x, top, bw, 22, col, op=0.07)
        s.text(x + bw - 8, top + 16, "PASS" if ok else "FAIL", 9.5, col, anchor="end",
               weight="bold", spacing="0.5")
        if veto:
            s.text(x + 8, top + 16, "VETO", 9, VETO, weight="bold", spacing="0.5")
        for k, ln in enumerate(wrap(g["name"], chars)):
            s.text(x + 8, top + 38 + k * 12, ln, 9.5, MUTED)
        if g["value"] is None:
            s.text(x + 8, top + 74, (g.get("detail") or "")[:chars], 11, INK, weight="bold")
            s.text(x + 8, top + 89, "no number to compare", 8.5, MUTED)
        else:
            s.text(x + 8, top + 76, fmt(g["value"], g["unit"]), 19, INK, weight="bold",
                   font=MONO)
            s.text(x + 8, top + 90, "needs %s %s %s" % (g["op"], fmt(g["bar"], g["unit"]),
                                                        g["unit"])[:chars + 6], 8.5, MUTED)
            try:                                   # how close this gate came to failing
                room = (g["value"] / g["bar"]) if g["op"] in (">=", ">") \
                    else (g["bar"] / g["value"])
                if room and 0 < room < 999:
                    s.text(x + bw - 8, top + 76, "%.2gx" % room, 10,
                           MUTED if room > 1.3 else VETO, anchor="end", weight="bold")
                    s.text(x + bw - 8, top + 90, "room", 8.5, MUTED, anchor="end")
            except (TypeError, ZeroDivisionError):
                pass
        if i < n - 1:
            s.text(x + bw + gap / 2.0, top + h / 2.0 + 5, "›", 15, FAINT,
                   anchor="middle")
        lines.append("%s: %s (%s)" % (g["name"], "pass" if ok else "FAIL",
                                      "%s needs %s %s" % (fmt(g["value"]), g["op"],
                                                          fmt(g["bar"]))
                                      if g["value"] is not None else (g.get("detail") or "")))
    return top + h + 18, lines


# ----------------------------------------------------------------------------- the field
def draw_field(s, y, verdict, selected):
    s.text(PAD, y + 14, "3 · THE FIELD", 11, MUTED, weight="bold", spacing="1.4")
    s.text(PAD + 118, y + 14, "what else was considered, and the number that settled it",
           11, MUTED)
    rows, lines = [], []
    for rule_key, card_id in RULE_TO_CARD.items():
        r = verdict.get(rule_key)
        if not isinstance(r, dict):
            continue
        rows.append((card_id, bool(r.get("fires")), r.get("why", "")))
    rows.sort(key=lambda t: (not t[1], t[0]))
    top = y + 28
    rh = 26
    for i, (name, fired, why) in enumerate(rows):
        ry = top + i * rh
        mine = (name == selected)
        if mine:
            s.rect(PAD - 6, ry - 4, W - 2 * PAD + 12, rh - 2, "#0b6bcb", rx=5, op=0.07)
        s.circle(PAD + 6, ry + 9, 5, FIRE if fired else "#ffffff",
                 stroke=FIRE if fired else FAINT, sw=1.6)
        s.text(PAD + 20, ry + 13, name, 11.5, INK if fired else MUTED,
               weight="bold" if mine else "normal")
        s.text(PAD + 250, ry + 13, (why or "")[:118], 10, MUTED)
        lines.append("%s %s - %s" % ("FIRED " if fired else "no    ", name, (why or "")[:150]))
    return top + len(rows) * rh + 10, lines


# ----------------------------------------------------------------------------------- card
def build(pack, ruler, blueprint_id=None, problems=""):
    verdict = BD.decide(pack)
    selected = verdict.get("selected")
    if selected == "datastore-wait":
        selected = "db-latency-dependency-wait"
    bid = blueprint_id or selected
    if bid not in CARDS:
        bid = selected if selected in CARDS else None

    bp_json = None
    if problems and bid:
        p = os.path.join(problems, bid, "blueprint.json")
        if os.path.exists(p):
            bp_json = json.load(io.open(p, encoding="utf-8"))

    s = Svg()
    cfg = CARDS.get(bid)
    fired = bool(bid and selected == bid)

    # -------- header
    head_h = 92
    s.rect(0, 0, W, head_h, "#ffffff")
    s.rect(0, 0, 6, head_h, ACCENT if fired else "#8c959f")
    title = (bp_json or {}).get("title") if bp_json else None
    s.text(PAD, 34, (bid or "no blueprint matched").upper(), 17, INK, weight="bold",
           spacing="0.6")
    s.text(PAD, 55, (title or "")[:104], 11, MUTED)
    s.text(PAD, 76, "run %s  ·  %s" % (pack.get("run_id", "?"), pack.get("app", "?")),
           10.5, MUTED, font=MONO)

    badge = "FIRES" if fired else ("DID NOT FIRE" if bid else "NOTHING MATCHED")
    bcol = FIRE if fired else MUTED
    bw = 132
    s.rect(W - PAD - bw, 22, bw, 30, bcol, rx=15, op=0.12)
    s.text(W - PAD - bw / 2.0, 42, badge, 12, bcol, anchor="middle", weight="bold",
           spacing="0.8")
    if fired:
        rc = ((bp_json or {}).get("decision") or {}).get("root_cause_is")
        svc = verdict.get("root_cause_service")
        s.text(W - PAD, 70, ("root cause: " + (rc or "see the verdict line"))[:74], 10,
               MUTED, anchor="end")
        s.text(W - PAD, 85, ("named: %s  ·  confidence %.2f"
                             % (svc or "not resolvable from the kernel trace",
                                verdict.get("confidence") or 0.0)), 10, MUTED, anchor="end")
    s.line(0, head_h, W, head_h, FAINT, 1)

    desc = ["%s on run %s (%s): %s."
            % (bid, pack.get("run_id"), pack.get("app"), badge.lower())]

    y = head_h + 16
    if cfg:
        y, l1 = draw_ruler(s, y, cfg, ruler, pack.get("run_id"), pack.get("app"))
        desc += l1
    s.line(PAD, y, W - PAD, y, FAINT, 1)

    rule_res = verdict.get(cfg["rule"]) if (cfg and cfg["rule"]) else None
    gates = (rule_res or {}).get("gates") or []
    note = None
    if cfg and not cfg["rule"]:
        note = ("This blueprint's rule is written and measured, but the rule engine does not "
                "implement it yet - so there are no gates to show.")
    elif rule_res and not gates:
        note = rule_res.get("why")
    y, l2 = draw_gates(s, y + 10, gates, note)
    desc += l2
    s.line(PAD, y, W - PAD, y, FAINT, 1)

    y, l3 = draw_field(s, y + 10, verdict, bid)
    desc += l3

    # -------- footer
    s.line(0, y + 4, W, y + 4, FAINT, 1)
    s.text(PAD, y + 24, "StrataTrace blueprint card · drawn from the kernel trace only · "
                        "ruler built from %d runs" % ruler.get("n_packs", 0), 9, MUTED)
    if (rule_res or {}).get("why"):
        s.text(PAD, y + 40, ("verdict: " + rule_res["why"])[:166], 9.5, INK)
    H = y + 52

    body = ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
            'viewBox="0 0 %d %d" font-family="%s">' % (W, H, W, H, FONT))
    body += "<title>%s</title>" % esc("blueprint card: %s / %s" % (bid, pack.get("run_id")))
    body += "<desc>%s</desc>" % esc(chr(10).join(desc))
    body += '<rect width="%d" height="%d" fill="#ffffff"/>' % (W, H)
    return body + "".join(s.parts) + "</svg>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True)
    ap.add_argument("--ruler", required=True)
    ap.add_argument("--blueprint", default="", help="which blueprint to show; default is "
                                                    "whichever one fired")
    ap.add_argument("--problems", default="", help="blueprints/problems, for titles")
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
