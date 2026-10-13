#!/usr/bin/env python3
"""Generate the paper's figures (PDF for LaTeX + PNG to eyeball).
Numbers are the medians recomputed in make_data.py. Okabe-Ito palette
(colorblind-safe by construction). One y-axis per panel; thin marks;
direct labels; legend only when >=2 series.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

OUT = Path(__file__).resolve().parent / "figures"
OUT.mkdir(exist_ok=True)

# Okabe-Ito
BLUE, ORANGE, GREEN, VERM, SKY, GREY = (
    "#0072B2", "#E69F00", "#009E73", "#D55E00", "#56B4E9", "#9aa0a6")

plt.rcParams.update({
    "font.size": 9, "axes.titlesize": 9, "axes.labelsize": 9,
    "legend.fontsize": 8, "xtick.labelsize": 8, "ytick.labelsize": 8,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": "#e6e6e6", "grid.linewidth": 0.6,
    "axes.axisbelow": True, "figure.dpi": 150, "savefig.bbox": "tight",
    "lines.linewidth": 2, "lines.markersize": 6,
})


def save(fig, name):
    for ext in ("pdf", "png"):
        fig.savefig(OUT / f"{name}.{ext}")
    plt.close(fig)


# ---------- Fig 1: CPU cap ----------
caps = ["uncapped", "1 core", "0.5 core", "0.25 core"]
x = range(len(caps))
t2_wall = [23.39, 24.39, 22.44, 28.94]
t3_wall = [18.66, 18.66, 23.66, 32.69]
t2_thr = [0.0, 0.32, 4.39, 13.69]
t3_thr = [0.0, 0.45, 6.3, 19.79]
fig, (axw, axt) = plt.subplots(1, 2, figsize=(7.0, 2.8))
axw.plot(x, t2_wall, "-o", color=BLUE, label="bug-fix")
axw.plot(x, t3_wall, "-s", color=ORANGE, label="implement")
axw.set_title("(a) wall time"); axw.set_ylabel("seconds")
axw.set_ylim(0, 36); axw.legend(frameon=False)
axt.plot(x, t2_thr, "-o", color=BLUE, label="bug-fix")
axt.plot(x, t3_thr, "-s", color=ORANGE, label="implement")
axt.set_title("(b) CFS throttle (cgroup ground truth)")
axt.set_ylabel("seconds throttled"); axt.set_ylim(0, 22)
for ax in (axw, axt):
    ax.set_xticks(list(x)); ax.set_xticklabels(caps, rotation=20, ha="right")
    ax.set_xlabel("cpu.max")
fig.suptitle("Problem 1 — CPU bandwidth cap: compute fixed, wait grows",
             fontsize=9.5, y=1.02)
save(fig, "fig_cpu")

# ---------- Fig 2: threads vs cores ----------
W = [2, 4, 8, 16]
phase = [0.42, 0.98, 1.87, 3.87]
# measured wait fraction vs (W-C)/W, C=4
meas_frac = [0.0, 0.05, 0.497, 0.747]
theory = [max(0, (w - 4) / w) for w in W]
fig, (axp, axf) = plt.subplots(1, 2, figsize=(7.0, 2.8))
axp.plot(W, phase, "-o", color=GREEN)
axp.axvline(4, color=GREY, ls=":", lw=1.2)
axp.text(4.2, 3.4, "cores = 4", color=GREY, fontsize=7.5)
axp.set_xscale("log", base=2); axp.set_xticks(W); axp.set_xticklabels(W)
axp.set_title("(a) parallel-phase wall"); axp.set_xlabel("workers W")
axp.set_ylabel("seconds")
for xi, yi in zip(W, phase):
    axp.annotate(f"{yi:g}s", (xi, yi), textcoords="offset points",
                 xytext=(0, 7), ha="center", fontsize=7.5)
axf.plot(W, [100 * t for t in theory], "-", color=GREY,
         label=r"theory $(W{-}C)/W$")
axf.plot(W, [100 * m for m in meas_frac], "o", color=VERM, label="measured")
axf.set_xscale("log", base=2); axf.set_xticks(W); axf.set_xticklabels(W)
axf.set_title("(b) time spent runnable-but-waiting")
axf.set_xlabel("workers W"); axf.set_ylabel("% of worker time")
axf.set_ylim(-5, 85); axf.legend(frameon=False)
fig.suptitle("Problem 2 — threads vs cores: run-queue contention follows "
             r"$(W{-}C)/W$", fontsize=9.5, y=1.02)
save(fig, "fig_threads")

# ---------- Fig 3: memory ----------
mh = ["unltd", "1536M", "1152M", "768M"]
mh_phase = [6.48, 6.5, 30.37, 30.38]
mh_ref = [0, 0, 1.05, 1.05]  # millions
fig, (axm, axc) = plt.subplots(1, 2, figsize=(7.2, 2.8),
                               gridspec_kw={"wspace": 0.32})
from matplotlib.patches import Patch
colors = [GREEN, GREEN, VERM, VERM]
axm.bar(range(len(mh)), mh_phase, color=colors, width=0.62)
axm.set_xticks(range(len(mh))); axm.set_xticklabels(mh)
axm.set_title("(a) memory.high: read-phase wall")
axm.set_xlabel("memory.high"); axm.set_ylabel("seconds"); axm.set_ylim(0, 40)
for i, (p, r) in enumerate(zip(mh_phase, mh_ref)):
    axm.annotate(f"{p:g}s", (i, p), textcoords="offset points",
                 xytext=(0, 3), ha="center", fontsize=8)
axm.legend(handles=[Patch(color=GREEN, label="fits"),
                    Patch(color=VERM, label="refaults")],
           frameon=False, loc="upper left", fontsize=8,
           handlelength=1.1, handleheight=1.1)
# OOM cliff
mx = [1024, 896, 768, 640]
outcome = [1, 1, 1, 0]  # 1 = task ok, 0 = OOM-killed
cols = [GREEN if o else VERM for o in outcome]
axc.scatter(mx, outcome, c=cols, s=90, zorder=3)
axc.axvspan(600, 712, color=VERM, alpha=0.08)
axc.yaxis.tick_right()          # labels on the right, clear of panel (a)
axc.set_yticks([0, 1]); axc.set_yticklabels(["OOM\n(task fails)", "survives"])
axc.set_title("(b) memory.max + anon: the OOM cliff")
axc.set_xlabel("memory.max (MB)")
axc.set_xticks(mx); axc.set_xticklabels(mx)
axc.set_ylim(-0.4, 1.4)
axc.annotate("agent+workload\n~762 MB", (704, 0.5), fontsize=7,
             ha="center", color=GREY)
fig.suptitle("Problem 3 — memory cap: recoverable slowdown vs OOM cliff",
             fontsize=9.5, y=1.02)
save(fig, "fig_memory")

# ---------- Fig 4: io cap ----------
rbps = [50, 100, 200, 300]  # 300 stands in for 'unlimited' at native ~205
rbps_lbl = ["50", "100", "200", "unltd"]
phase_io = [20.4, 10.1, 5.98, 5.98]
ideal = [1024 / r for r in [50, 100, 200, 205]]  # 1 GB / rbps (s)
fig, ax = plt.subplots(figsize=(4.2, 2.9))
ax.plot(range(4), phase_io, "-o", color=BLUE, label="measured", zorder=3)
ax.plot(range(4), ideal, "--", color=GREY, label=r"ideal $1\,$GB$/r$")
ax.axhline(5.98, color=VERM, ls=":", lw=1.2)
ax.text(0.05, 6.8, "native disk floor ~205 MB/s", color=VERM, fontsize=7)
ax.set_xticks(range(4)); ax.set_xticklabels(rbps_lbl)
ax.set_xlabel("io.max rbps (MB/s)"); ax.set_ylabel("read-phase wall (s)")
ax.set_ylim(0, 23); ax.legend(frameon=False)
for i, y in enumerate(phase_io):
    ax.annotate(f"{y:g}s", (i, y), textcoords="offset points",
                xytext=(6, 4), fontsize=7.5)
ax.set_title("Problem 4 — disk I/O cap: wall $\\sim$ bytes/rbps", fontsize=9.5)
save(fig, "fig_io")

print("wrote:", sorted(p.name for p in OUT.glob("*.pdf")))
