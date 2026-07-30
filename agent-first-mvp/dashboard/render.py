#!/usr/bin/env python3
"""Render a phase-2 result.json into a self-contained, offline incident dashboard.

No external resources (works on the VM / any browser, no server). All charts are
Python-computed inline SVG. Usage:
    python render.py result.json out.html
"""
import json, sys, os, html, math

PALETTE = {
    "on_cpu": "#38bdf8", "runnable_wait": "#fbbf24",
    "disk_wait": "#f472b6", "off_cpu_io_wait": "#a78bfa",
}
LABEL = {"on_cpu":"on-CPU (compute)", "runnable_wait":"runnable-wait (CPU starvation)",
         "disk_wait":"blocked on disk", "off_cpu_io_wait":"off-CPU I/O-readiness wait"}
MOD_COLOR = {"KERNEL":"#a78bfa","TRACES":"#34d399","METRICS":"#38bdf8","LOGS":"#fbbf24"}

def esc(s): return html.escape(str(s))

def donut(pcts, cx=110, cy=110, r=84, w=30):
    """pcts: list of (key,label,value,color). Returns SVG string."""
    total = sum(v for *_, v, _ in pcts) or 1
    segs, a0 = [], -90.0
    for key, lbl, v, col in pcts:
        frac = v/total; a1 = a0 + frac*360
        large = 1 if (a1-a0) > 180 else 0
        x0 = cx + r*math.cos(math.radians(a0)); y0 = cy + r*math.sin(math.radians(a0))
        x1 = cx + r*math.cos(math.radians(a1)); y1 = cy + r*math.sin(math.radians(a1))
        if frac > 0.001:
            segs.append(f'<path d="M {x0:.2f} {y0:.2f} A {r} {r} 0 {large} 1 {x1:.2f} {y1:.2f}" '
                        f'fill="none" stroke="{col}" stroke-width="{w}"><title>{esc(lbl)}: {v}%</title></path>')
        a0 = a1
    dom = max(pcts, key=lambda p: p[2])
    return (f'<svg viewBox="0 0 220 220" class="donut">{"".join(segs)}'
            f'<text x="{cx}" y="{cy-6}" class="donut-big">{dom[2]:.0f}%</text>'
            f'<text x="{cx}" y="{cy+16}" class="donut-sub">{esc(dom[1])}</text></svg>')

def gauge(conf):
    frac = max(0, min(1, conf)); ang = -90 + frac*180
    r, cx, cy = 70, 90, 90
    x = cx + r*math.cos(math.radians(ang)); y = cy + r*math.sin(math.radians(ang))
    x0, y0 = cx - r, cy; large = 1 if frac > 0.5 else 0
    col = "#34d399" if frac >= 0.8 else "#fbbf24" if frac >= 0.6 else "#f87171"
    return (f'<svg viewBox="0 0 180 110" class="gauge">'
            f'<path d="M {x0} {y0} A {r} {r} 0 1 1 {cx+r} {cy}" fill="none" stroke="#1e293b" stroke-width="12"/>'
            f'<path d="M {x0} {y0} A {r} {r} 0 {large} 1 {x:.1f} {y:.1f}" fill="none" stroke="{col}" '
            f'stroke-width="12" stroke-linecap="round"/>'
            f'<text x="{cx}" y="{cy-6}" class="gauge-big">{frac*100:.0f}%</text>'
            f'<text x="{cx}" y="{cy+12}" class="gauge-sub">confidence</text></svg>')

def bar(label, val, maxv, color, unit="MB"):
    pct = 100*val/maxv if maxv else 0
    return (f'<div class="barrow"><span class="barlbl">{esc(label)}</span>'
            f'<span class="bartrack"><span class="barfill" style="width:{pct:.1f}%;background:{color}"></span></span>'
            f'<span class="barval">{val:,.0f} {unit}</span></div>')

def render(res):
    v = res["verdict"]; ev = res["evidence_bundle"]
    k = ev.get("kernel", {}); subj = "catalogue" if "catalogue" in k else (list(k)[0] if k else None)
    ro = k.get(subj, {}).get("rule_out_pct", {}) if subj else {}
    donut_data = [(key, LABEL[key], ro.get(key,0), PALETTE[key]) for key in
                  ("off_cpu_io_wait","on_cpu","runnable_wait","disk_wait") if key in ro]
    gt = res.get("ground_truth", {}).get("fault", {})
    correct = res.get("correct")

    # collection spec
    spec = res.get("phase1", {}).get("collection_spec", {})
    kern = spec.get("kernel", {}) or {}
    chips = lambda xs: "".join(f'<span class="chip">{esc(x)}</span>' for x in (xs or []))

    # evidence with modality tag color
    ev_html = ""
    for line in v.get("evidence", []):
        tag = line.split(":",1)[0].strip(); body = line.split(":",1)[1] if ":" in line else line
        col = MOD_COLOR.get(tag, "#94a3b8")
        ev_html += (f'<li><span class="modtag" style="background:{col}22;color:{col};border-color:{col}55">'
                    f'{esc(tag)}</span><span>{esc(body)}</span></li>')

    ruled_html = "".join(f'<li><span class="x">✕</span>{esc(r)}</li>' for r in v.get("ruled_out", []))

    # data-touched bars (scoped vs undirected)
    touched = ev.get("data_touched_mb", 0); undirected = ev.get("undirected_processing_mb", touched)
    red = v.get("reduction_x")
    bars = bar("Scoped by skill (what we read)", touched, undirected, "#34d399") + \
           bar("Undirected kernel-deep (full run)", undirected, undirected, "#334155")

    spans = ev.get("spans", {}); metrics = ev.get("metrics", {}).get("checks", [])
    took = ev.get("logs", {}).get("took", {})
    m0 = next((c for c in metrics if c.get("passed")), metrics[0] if metrics else None)

    cross = ""
    if spans:
        for s, d in spans.items():
            cross += (f'<div class="xm"><div class="xm-k">TRACES · {esc(s)}</div>'
                      f'<div class="xm-v">{d.get("p95_s","?")}s <small>p95</small></div>'
                      f'<div class="xm-n">{d.get("n","?")} server spans</div></div>')
    if m0:
        cross += (f'<div class="xm"><div class="xm-k">METRICS · {esc(m0.get("name",""))}</div>'
                  f'<div class="xm-v">{m0.get("baseline")}→{m0.get("injection")}s</div>'
                  f'<div class="xm-n">{float(m0.get("delta_sigma") or 0):,.0f}σ · {esc(ev.get("metrics",{}).get("status",""))}</div></div>')
    for s, d in took.items():
        cross += (f'<div class="xm"><div class="xm-k">LOGS · {esc(s)}</div>'
                  f'<div class="xm-v">{d.get("p95_ms","?")}<small>ms</small></div>'
                  f'<div class="xm-n">{d.get("n","?")} requests · took p95</div></div>')

    gt_reveal = ""
    if gt:
        params = gt.get("parameters", {})
        gt_reveal = (
            f'<details class="oracle"><summary>Ground truth (hidden from the analyzer) '
            f'<span class="{"ok" if correct else "bad"}">{"✓ CORRECT" if correct else "✗ MISS"}</span></summary>'
            f'<div class="oracle-body"><b>Injected fault:</b> {esc(gt.get("name"))} '
            f'· intensity {esc(gt.get("intensity"))}<br>'
            f'<b>Parameters:</b> {esc(json.dumps(params))}<br>'
            f'<b>Target:</b> {esc(gt.get("target_service"))} · trace visibility: '
            f'<b>{esc(gt.get("target_trace_visibility"))}</b><br>'
            f'<b>Remediation:</b> {esc(res.get("ground_truth",{}).get("remediation",{}).get("action",""))}</div></details>')

    dm = v.get("decisive_modality","")
    return f"""<div class="wrap">
<header class="top">
  <div class="brand"><span class="dot"></span> collection-aware RCA <span class="mode">{esc(res.get("mode","replay"))}</span></div>
  <div class="prob">“{esc(res.get("problem_statement",""))}”</div>
  <div class="skill">skill: <code>{esc(res.get("skill",""))}</code> · run <code>{esc(res.get("run",""))}</code></div>
</header>

<section class="verdict">
  <div class="v-main">
    <div class="v-tag">ROOT CAUSE</div>
    <h1>{esc(v.get("root_cause",""))}</h1>
    <div class="v-decisive">decisive modality: <b>{esc(dm)}</b></div>
    <div class="v-fix"><b>Recommended fix.</b> {esc(v.get("recommended_fix",""))}</div>
  </div>
  <div class="v-gauge">{gauge(v.get("confidence",0))}</div>
</section>

<div class="grid">
  <section class="card">
    <h2>Kernel wait-attribution <small>· {esc(subj or "")} · {k.get(subj,{}).get("n_tids_seen","?")} threads</small></h2>
    <div class="donut-row">{donut(donut_data) if donut_data else ""}
      <ul class="legend">{"".join(f'<li><span class="sw" style="background:{PALETTE[key]}"></span>{esc(LABEL[key])} <b>{ro.get(key,0)}%</b></li>' for key in ("off_cpu_io_wait","on_cpu","runnable_wait","disk_wait") if key in ro)}</ul>
    </div>
  </section>

  <section class="card">
    <h2>Ruled out <small>· by the same evidence</small></h2>
    <ul class="ruled">{ruled_html}</ul>
  </section>
</div>

<section class="card">
  <h2>The agent decided to collect <em>only</em> this <small>· phase-1 collection spec</small></h2>
  <div class="spec">
    <div class="spec-blk"><div class="spec-h">kernel · {esc(kern.get("mode",""))} · ≤{esc(kern.get("max_duration_s",""))}s</div>
      <div class="spec-sub">events</div>{chips(kern.get("events"))}
      <div class="spec-sub">syscalls</div>{chips(kern.get("syscalls"))}
      <div class="spec-sub">scope</div>{chips((kern.get("scope",{}) or {}).get("target_services"))}</div>
    <div class="spec-blk"><div class="spec-h">other modalities</div>
      <div class="spec-sub">otel</div>{chips((spec.get("otel",{}) or {}).get("services"))}
      <div class="spec-sub">logs</div>{chips((spec.get("logs",{}) or {}).get("services"))}
      <div class="spec-sub">metrics</div>{chips([m[:48]+"…" for m in (spec.get("metrics") or [])])}</div>
  </div>
  <div class="capcmd"><span>capture command</span><code>{esc(kern.get("capture_cmd",""))}</code></div>
</section>

<section class="card">
  <h2>Cross-modal evidence</h2>
  <div class="xmrow">{cross}</div>
  <ul class="evlist">{ev_html}</ul>
</section>

<section class="card payoff">
  <h2>Collection-aware payoff <small>· data actually read vs undirected kernel-deep</small></h2>
  <div class="bighead"><span class="redx">{red}×</span> less data to answer the question</div>
  {bars}
  <div class="payoff-note">This run’s scope touched <b>{touched:,.0f} MB</b>; an undirected kernel-deep analysis of the same run would ingest <b>{undirected:,.0f} MB</b> (full decompressed kernel + all spans/logs). On-disk bundle: {ev.get("on_disk_bundle_mb",0):,.0f} MB.</div>
</section>

{gt_reveal}
<footer>StrataTrace · agent-first collection-aware observability · offline dashboard</footer>
</div>"""

CSS = """
:root{--bg:#0b1120;--panel:#0f172a;--panel2:#111c31;--line:#1e293b;--tx:#e2e8f0;--mut:#94a3b8;--ac:#a78bfa;}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 600px at 70% -10%,#15213b,transparent),var(--bg);color:var(--tx);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Inter,sans-serif;}
.wrap{max-width:1040px;margin:0 auto;padding:28px 22px 60px}
.top{display:flex;flex-direction:column;gap:6px;margin-bottom:22px}
.brand{font-weight:700;letter-spacing:.04em;text-transform:uppercase;font-size:12px;color:var(--mut);display:flex;align-items:center;gap:8px}
.dot{width:9px;height:9px;border-radius:50%;background:#34d399;box-shadow:0 0 12px #34d399}
.mode{margin-left:6px;padding:2px 8px;border:1px solid var(--line);border-radius:20px;color:var(--ac);font-size:10px}
.prob{font-size:26px;font-weight:600;color:#fff}
.skill{color:var(--mut);font-size:13px}
.skill code,.capcmd code{background:#0b1424;padding:1px 7px;border-radius:6px;border:1px solid var(--line);color:#cbd5e1}
.verdict{display:grid;grid-template-columns:1fr 200px;gap:18px;align-items:center;background:linear-gradient(180deg,#141f38,#0f1830);border:1px solid var(--line);border-left:4px solid var(--ac);border-radius:16px;padding:22px 24px;margin-bottom:18px}
.v-tag{font-size:11px;letter-spacing:.12em;color:var(--ac);font-weight:700}
.verdict h1{font-size:21px;line-height:1.35;margin:6px 0 12px;color:#fff;font-weight:650}
.v-decisive{color:var(--mut);font-size:13px;margin-bottom:10px}
.v-decisive b{color:#34d399}
.v-fix{background:#0b1424;border:1px solid var(--line);border-radius:10px;padding:10px 12px;font-size:13px;color:#cbd5e1}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin-bottom:16px}
.card h2{margin:0 0 14px;font-size:15px;font-weight:650;color:#f1f5f9}
.card h2 small,.card h2 em{color:var(--mut);font-weight:400;font-style:normal}
.donut-row{display:flex;gap:18px;align-items:center}
.donut{width:170px;height:170px;flex:none}
.donut path{stroke-linecap:butt}
.donut-big{fill:#fff;font-size:30px;font-weight:700;text-anchor:middle}
.donut-sub{fill:var(--mut);font-size:9px;text-anchor:middle}
.legend{list-style:none;margin:0;padding:0;font-size:13px}
.legend li{display:flex;align-items:center;gap:8px;margin:7px 0;color:#cbd5e1}
.legend b{margin-left:auto;color:#fff}
.sw{width:11px;height:11px;border-radius:3px;flex:none}
.ruled{list-style:none;margin:0;padding:0}
.ruled li{display:flex;gap:10px;padding:9px 0;border-bottom:1px solid var(--line);color:#94a3b8;font-size:13px}
.ruled li:last-child{border:0}
.x{color:#f87171;font-weight:700}
.gauge{width:180px}
.gauge-big{fill:#fff;font-size:26px;font-weight:700;text-anchor:middle}
.gauge-sub{fill:var(--mut);font-size:10px;text-anchor:middle}
.spec{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.spec-h{font-size:12px;color:var(--ac);font-weight:700;margin-bottom:8px;text-transform:uppercase;letter-spacing:.05em}
.spec-sub{font-size:11px;color:var(--mut);margin:8px 0 4px;text-transform:uppercase;letter-spacing:.04em}
.chip{display:inline-block;background:#0b1424;border:1px solid var(--line);color:#93c5fd;border-radius:7px;padding:3px 8px;margin:2px 4px 2px 0;font-size:12px;font-family:ui-monospace,monospace}
.capcmd{margin-top:14px;font-size:12px}
.capcmd span{color:var(--mut);text-transform:uppercase;letter-spacing:.05em;font-size:10px;display:block;margin-bottom:4px}
.capcmd code{display:block;padding:10px 12px;white-space:pre-wrap;word-break:break-word;line-height:1.6}
.xmrow{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px}
.xm{flex:1;min-width:150px;background:#0b1424;border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.xm-k{font-size:10px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px}
.xm-v{font-size:22px;font-weight:700;color:#fff}.xm-v small{font-size:12px;color:var(--mut);font-weight:400}
.xm-n{font-size:12px;color:var(--mut);margin-top:2px}
.evlist{list-style:none;margin:0;padding:0}
.evlist li{display:flex;gap:12px;align-items:baseline;padding:10px 0;border-top:1px solid var(--line);font-size:13.5px;color:#cbd5e1}
.modtag{flex:none;font-size:10px;font-weight:700;padding:2px 8px;border-radius:6px;border:1px solid;letter-spacing:.04em}
.payoff .bighead{font-size:15px;color:var(--mut);margin-bottom:16px}
.redx{font-size:40px;font-weight:800;color:#34d399;vertical-align:-4px;margin-right:8px}
.barrow{display:flex;align-items:center;gap:12px;margin:9px 0;font-size:13px}
.barlbl{width:240px;color:#cbd5e1;flex:none}
.bartrack{flex:1;height:14px;background:#0b1424;border-radius:8px;overflow:hidden;border:1px solid var(--line)}
.barfill{display:block;height:100%;border-radius:8px}
.barval{width:90px;text-align:right;color:#fff;font-weight:600;flex:none}
.payoff-note{margin-top:14px;font-size:12.5px;color:var(--mut)}
.oracle{background:#0b1424;border:1px solid var(--line);border-radius:12px;padding:4px 16px;margin-bottom:16px}
.oracle summary{cursor:pointer;padding:12px 0;font-weight:600;color:#cbd5e1}
.oracle .ok{color:#34d399;margin-left:8px}.oracle .bad{color:#f87171;margin-left:8px}
.oracle-body{padding:6px 0 14px;font-size:13px;color:#94a3b8;line-height:1.8}
.oracle-body b{color:#cbd5e1}
footer{text-align:center;color:#475569;font-size:11px;margin-top:30px;letter-spacing:.04em}
@media(max-width:760px){.verdict,.grid,.spec{grid-template-columns:1fr}.barlbl{width:130px}}
@media(prefers-color-scheme:light){:root{--bg:#f1f5f9;--panel:#fff;--panel2:#f8fafc;--line:#e2e8f0;--tx:#0f172a;--mut:#64748b}body{background:#eef2f7}.chip,.xm,.v-fix,.capcmd code,.oracle,.skill code{background:#f8fafc}}
"""

def full_page(res):
    return f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>RCA · {esc(res.get('skill',''))}</title><style>{CSS}</style></head><body>{render(res)}</body></html>"

if __name__ == "__main__":
    res = json.load(open(sys.argv[1]))
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(sys.argv[1])[0]+".html"
    open(out, "w", encoding="utf-8").write(full_page(res))
    print("wrote", out)
