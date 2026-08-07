#!/usr/bin/env python3
"""Render a phase-2 result.json into a self-contained, offline incident dashboard.

Design: a kernel-tracing *instrument panel* — blue-biased ink ground, monospace
tabular numerics carrying the data, semantic color on the wait-attribution
(green = on-CPU/healthy, amber = CPU-starvation, red = disk, azure = the finding).
No external resources: all charts are Python-computed inline SVG; typography uses
robust system mono/sans stacks (no CDN fonts → no silent fallback). Both themes.

    python render.py result.json out.html
"""
import json, sys, os, html, math

# wait-attribution buckets, colored by MEANING (not a rainbow)
PALETTE = {"off_cpu_io_wait":"var(--accent)", "on_cpu":"var(--good)",
           "runnable_wait":"var(--warn)", "disk_wait":"var(--crit)"}
LABEL = {"on_cpu":"on-CPU (compute)", "runnable_wait":"runnable-wait (CPU starvation)",
         "disk_wait":"blocked on disk", "off_cpu_io_wait":"off-CPU I/O-readiness wait"}
MOD = {"KERNEL":"var(--accent)","TRACES":"var(--good)","METRICS":"var(--info)","LOGS":"var(--warn)"}

def esc(s): return html.escape(str(s))

def donut(pcts, cx=100, cy=100, r=76, w=26):
    total = sum(v for *_, v, _ in pcts) or 1
    ring = f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="var(--track)" stroke-width="{w}"/>'
    segs, a0 = [], -90.0
    for key, lbl, v, col in pcts:
        frac = v/total; a1 = a0 + frac*360; large = 1 if (a1-a0) > 180 else 0
        x0 = cx + r*math.cos(math.radians(a0)); y0 = cy + r*math.sin(math.radians(a0))
        x1 = cx + r*math.cos(math.radians(a1)); y1 = cy + r*math.sin(math.radians(a1))
        if frac > 0.004:
            segs.append(f'<path d="M {x0:.2f} {y0:.2f} A {r} {r} 0 {large} 1 {x1:.2f} {y1:.2f}" '
                        f'fill="none" stroke="{col}" stroke-width="{w}"><title>{esc(lbl)}: {v}%</title></path>')
        a0 = a1
    dom = max(pcts, key=lambda p: p[2])
    return (f'<svg viewBox="0 0 200 200" class="donut" role="img" aria-label="wait attribution">{ring}{"".join(segs)}'
            f'<text x="{cx}" y="{cy-4}" class="donut-big">{dom[2]:.0f}<tspan class="pct">%</tspan></text>'
            f'<text x="{cx}" y="{cy+15}" class="donut-sub">{esc(dom[0].replace("_"," "))}</text></svg>')

def gauge(conf):
    frac = max(0, min(1, conf)); ang = -90 + frac*180
    r, cx, cy = 62, 80, 80
    x = cx + r*math.cos(math.radians(ang)); y = cy + r*math.sin(math.radians(ang))
    x0, y0 = cx - r, cy; large = 1 if frac > 0.5 else 0
    col = "var(--good)" if frac >= 0.8 else "var(--warn)" if frac >= 0.6 else "var(--crit)"
    return (f'<svg viewBox="0 0 160 96" class="gauge" role="img" aria-label="confidence">'
            f'<path d="M {x0} {y0} A {r} {r} 0 1 1 {cx+r} {cy}" fill="none" stroke="var(--track)" stroke-width="10"/>'
            f'<path d="M {x0} {y0} A {r} {r} 0 {large} 1 {x:.1f} {y:.1f}" fill="none" stroke="{col}" '
            f'stroke-width="10" stroke-linecap="round"/>'
            f'<text x="{cx}" y="{cy-2}" class="gauge-big">{frac*100:.0f}<tspan class="pct">%</tspan></text></svg>')

def render(res):
    v = res["verdict"]; ev = res["evidence_bundle"]
    k = ev.get("kernel", {}); subj = "catalogue" if "catalogue" in k else (list(k)[0] if k else None)
    ro = k.get(subj, {}).get("rule_out_pct", {}) if subj else {}
    order = ("off_cpu_io_wait","on_cpu","runnable_wait","disk_wait")
    donut_data = [(key, LABEL[key], ro.get(key,0), PALETTE[key]) for key in order if key in ro]
    gt = res.get("ground_truth", {}).get("fault", {}); correct = res.get("correct")
    conf = v.get("confidence",0)
    stripe = "var(--good)" if conf >= 0.8 else "var(--warn)" if conf >= 0.6 else "var(--crit)"

    spec = res.get("phase1", {}).get("collection_spec", {}); kern = spec.get("kernel", {}) or {}
    chips = lambda xs: "".join(f'<span class="chip">{esc(x)}</span>' for x in (xs or [])) or '<span class="chip none">—</span>'

    ev_html = ""
    for line in v.get("evidence", []):
        tag = line.split(":",1)[0].strip(); body = line.split(":",1)[1] if ":" in line else line
        col = MOD.get(tag, "var(--muted)")
        ev_html += (f'<li><span class="modtag" style="--m:{col}">{esc(tag)}</span><span>{esc(body)}</span></li>')
    ruled_html = "".join(f'<li><span class="x">ruled&nbsp;out</span>{esc(r)}</li>' for r in v.get("ruled_out", []))

    touched = ev.get("data_touched_mb", 0); undirected = ev.get("undirected_processing_mb", touched) or touched
    red = v.get("reduction_x")
    def bar(label, val, maxv, cls):
        pct = 100*val/maxv if maxv else 0
        return (f'<div class="barrow"><span class="barlbl">{esc(label)}</span>'
                f'<span class="bartrack"><span class="barfill {cls}" style="width:{max(pct,0.6):.1f}%"></span></span>'
                f'<span class="barval">{val:,.0f}<small>MB</small></span></div>')
    bars = (bar("Scoped by the skill — actually read", touched, undirected, "on") +
            bar("Undirected kernel-deep — full run", undirected, undirected, "off"))

    spans = ev.get("spans", {}); metrics = ev.get("metrics", {}).get("checks", [])
    took = ev.get("logs", {}).get("took", {})
    m0 = next((c for c in metrics if c.get("passed")), metrics[0] if metrics else None)
    cross = ""
    for s, d in spans.items():
        cross += (f'<div class="xm"><div class="xm-k"><i style="--m:var(--good)"></i>TRACES · {esc(s)}</div>'
                  f'<div class="xm-v">{d.get("p95_s","?")}<small>s p95</small></div>'
                  f'<div class="xm-n">{d.get("n","?"):,} server spans · max {d.get("max_s","?")}s</div></div>')
    if m0:
        ds = float(m0.get("delta_sigma") or 0)
        cross += (f'<div class="xm"><div class="xm-k"><i style="--m:var(--info)"></i>METRICS · p95</div>'
                  f'<div class="xm-v">{m0.get("baseline")}<small>→</small>{m0.get("injection")}<small>s</small></div>'
                  f'<div class="xm-n">{ds:,.0f}σ shift · {esc(ev.get("metrics",{}).get("status",""))}</div></div>')
    for s, d in took.items():
        cross += (f'<div class="xm"><div class="xm-k"><i style="--m:var(--warn)"></i>LOGS · {esc(s)}</div>'
                  f'<div class="xm-v">{d.get("p95_ms","?")}<small>ms p95</small></div>'
                  f'<div class="xm-n">{d.get("n","?"):,} requests logged took=</div></div>')

    gt_reveal = ""
    if gt:
        gt_reveal = (
            f'<details class="oracle"><summary><span>Ground truth · hidden from the analyzer</span>'
            f'<span class="verdict-pill {"ok" if correct else "bad"}">{"✓ correct" if correct else "✗ miss"}</span></summary>'
            f'<div class="oracle-body">'
            f'<div><span>injected fault</span><b>{esc(gt.get("name"))}</b> · {esc(gt.get("intensity"))}</div>'
            f'<div><span>parameters</span><code>{esc(json.dumps(gt.get("parameters",{})))}</code></div>'
            f'<div><span>trace visibility</span><b>{esc(gt.get("target_trace_visibility"))}</b> — why kernel depth matters</div>'
            f'<div><span>remediation</span>{esc(res.get("ground_truth",{}).get("remediation",{}).get("action",""))}</div>'
            f'</div></details>')

    legend = "".join(f'<li><span class="sw" style="background:{PALETTE[key]}"></span>'
                     f'<span>{esc(LABEL[key])}</span><b>{ro.get(key,0)}%</b></li>'
                     for key in order if key in ro)
    return f"""<main class="wrap">
<header class="top">
  <div class="brand"><span class="live {esc(res.get("mode","replay"))}"></span>collection-aware RCA
    <span class="mode">{esc(res.get("mode","replay"))}</span></div>
  <h1 class="prob">{esc(res.get("problem_statement",""))}</h1>
  <div class="meta">skill <code>{esc(res.get("skill",""))}</code> · run <code>{esc(res.get("run",""))}</code></div>
</header>

<section class="verdict" style="--stripe:{stripe}">
  <div class="v-main">
    <div class="v-tag">root cause</div>
    <h2>{esc(v.get("root_cause",""))}</h2>
    <div class="v-decisive">decisive modality <b>{esc(v.get("decisive_modality",""))}</b></div>
    <p class="v-fix"><span>recommended fix</span>{esc(v.get("recommended_fix",""))}</p>
  </div>
  <div class="v-gauge">{gauge(conf)}<div class="gauge-cap">confidence</div></div>
</section>

{f'''<div class="grid2">
  <section class="card">
    <h3>Kernel wait-attribution<small>{esc(subj or "")} · {k.get(subj,{}).get("n_tids_seen","?")} threads · babeltrace2</small></h3>
    <div class="donut-row">{donut(donut_data)}<ul class="legend">{legend}</ul></div>
  </section>
  <section class="card">
    <h3>Ruled out<small>by the same evidence</small></h3>
    <ul class="ruled">{ruled_html}</ul>
  </section>
</div>''' if donut_data else f'''<section class="card">
    <h3>Ruled out<small>by the same evidence</small></h3>
    <ul class="ruled">{ruled_html}</ul>
</section>'''}

<section class="card">
  <h3>The agent chose to collect <em>only</em> this<small>phase-1 collection spec</small></h3>
  <div class="spec">
    <div class="spec-blk"><div class="spec-h">kernel · {esc(kern.get("mode",""))} · ≤{esc(kern.get("max_duration_s",""))}s</div>
      <div class="spec-sub">scheduler events</div>{chips(kern.get("events"))}
      <div class="spec-sub">syscalls</div>{chips(kern.get("syscalls"))}
      <div class="spec-sub">scope</div>{chips((kern.get("scope",{}) or {}).get("target_services"))}</div>
    <div class="spec-blk"><div class="spec-h">correlating modalities</div>
      <div class="spec-sub">otel traces</div>{chips((spec.get("otel",{}) or {}).get("services"))}
      <div class="spec-sub">logs</div>{chips((spec.get("logs",{}) or {}).get("services"))}
      <div class="spec-sub">metric</div>{chips(["p95 latency PromQL"] if spec.get("metrics") else [])}</div>
  </div>
  <div class="capcmd"><span>capture command</span><code>{esc(kern.get("capture_cmd",""))}</code></div>
</section>

<section class="card">
  <h3>Cross-modal evidence<small>four modalities, one verdict</small></h3>
  <div class="xmrow">{cross}</div>
  <ul class="evlist">{ev_html}</ul>
</section>

<section class="card payoff">
  <h3>Collection-aware payoff<small>data read vs an undirected kernel-deep pass</small></h3>
  <div class="bighead"><span class="redx">{red}×</span><span>less data ingested to answer the question</span></div>
  {bars}
  <p class="payoff-note">This scope touched <b>{touched:,.0f} MB</b>; an undirected kernel-deep analysis of the
  same run would ingest <b>{undirected:,.0f} MB</b> (full decompressed kernel + all spans + all logs).
  On-disk bundle {ev.get("on_disk_bundle_mb",0):,.0f} MB.</p>
</section>

{gt_reveal}
<footer>StrataTrace · agent-first, collection-aware observability</footer>
</main>"""

CSS = """
:root{
  --bg:#0a0e15; --panel:#0f1621; --panel2:#0c131d; --line:#1d2836; --track:#161f2b;
  --tx:#d6e0ec; --muted:#7e8ea3; --accent:#4ea8de; --good:#3fb950; --warn:#d6a531;
  --crit:#f0663f; --info:#5bc8e6;
  --mono:ui-monospace,"SF Mono","JetBrains Mono","Cascadia Code",Menlo,Consolas,monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
}
@media(prefers-color-scheme:light){:root{
  --bg:#eef2f7; --panel:#ffffff; --panel2:#f6f9fc; --line:#dce3ec; --track:#e6ecf3;
  --tx:#16202c; --muted:#5c6b7d; --accent:#1f7fb8;}}
:root[data-theme="dark"]{--bg:#0a0e15;--panel:#0f1621;--panel2:#0c131d;--line:#1d2836;--track:#161f2b;--tx:#d6e0ec;--muted:#7e8ea3;--accent:#4ea8de;}
:root[data-theme="light"]{--bg:#eef2f7;--panel:#fff;--panel2:#f6f9fc;--line:#dce3ec;--track:#e6ecf3;--tx:#16202c;--muted:#5c6b7d;--accent:#1f7fb8;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);font-family:var(--sans);
  font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
.wrap{max-width:1000px;margin:0 auto;padding:30px 22px 64px}
code,.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.top{margin-bottom:22px}
.brand{display:flex;align-items:center;gap:9px;font-family:var(--mono);font-size:11px;
  letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.live{width:8px;height:8px;border-radius:50%;background:var(--good);box-shadow:0 0 0 0 var(--good);animation:pulse 2.4s infinite}
.live.replay{background:var(--accent);box-shadow:none;animation:none}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(63,185,80,.5)}70%{box-shadow:0 0 0 7px rgba(63,185,80,0)}100%{box-shadow:0 0 0 0 rgba(63,185,80,0)}}
.mode{padding:1px 8px;border:1px solid var(--line);border-radius:4px;color:var(--accent);font-size:10px}
.prob{font-size:29px;line-height:1.2;font-weight:600;margin:12px 0 6px;letter-spacing:-.01em;text-wrap:balance}
.prob::before{content:"“";color:var(--muted)}.prob::after{content:"”";color:var(--muted)}
.meta{font-family:var(--mono);font-size:12px;color:var(--muted)}
code{background:var(--panel2);border:1px solid var(--line);border-radius:4px;padding:1px 6px;font-size:.86em}
.verdict{display:grid;grid-template-columns:1fr 150px;gap:20px;align-items:center;
  background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:22px 24px;margin-bottom:16px;position:relative;overflow:hidden}
.verdict::before{content:"";position:absolute;inset:0 auto 0 0;width:3px;background:var(--stripe)}
.v-tag{font-family:var(--mono);font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--stripe);font-weight:700}
.verdict h2{font-size:20px;line-height:1.4;margin:8px 0 12px;font-weight:600;letter-spacing:-.01em;text-wrap:balance}
.v-decisive{font-family:var(--mono);font-size:12px;color:var(--muted);margin-bottom:12px}
.v-decisive b{color:var(--good)}
.v-fix{margin:0;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:11px 13px;font-size:13.5px;color:var(--tx)}
.v-fix span{display:block;font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:3px}
.v-gauge{text-align:center}.gauge{width:150px}.gauge-cap{font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-top:-6px}
.gauge-big{fill:var(--tx);font-size:30px;font-weight:700;text-anchor:middle;font-family:var(--mono)}
.pct{font-size:15px;fill:var(--muted)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin-bottom:16px}
.card h3{margin:0 0 15px;font-size:12px;font-family:var(--mono);letter-spacing:.06em;text-transform:uppercase;
  color:var(--tx);display:flex;justify-content:space-between;align-items:baseline;gap:10px;border-bottom:1px solid var(--line);padding-bottom:11px}
.card h3 small,.card h3 em{color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0;font-style:normal;font-size:11px}
.donut-row{display:flex;gap:20px;align-items:center}
.donut{width:158px;height:158px;flex:none}
.donut-big{fill:var(--tx);font-size:34px;font-weight:700;text-anchor:middle;font-family:var(--mono)}
.donut-sub{fill:var(--muted);font-size:8.5px;text-anchor:middle;font-family:var(--mono);letter-spacing:.05em}
.legend{list-style:none;margin:0;padding:0;font-size:12.5px;flex:1}
.legend li{display:flex;align-items:center;gap:9px;padding:6px 0;border-bottom:1px solid var(--line)}
.legend li:last-child{border:0}.legend b{margin-left:auto;font-family:var(--mono);font-variant-numeric:tabular-nums}
.sw{width:10px;height:10px;border-radius:2px;flex:none}
.ruled{list-style:none;margin:0;padding:0}
.ruled li{display:flex;gap:11px;align-items:baseline;padding:11px 0;border-bottom:1px solid var(--line);color:var(--muted);font-size:13px}
.ruled li:last-child{border:0}
.x{flex:none;font-family:var(--mono);font-size:9.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--crit);
  border:1px solid color-mix(in srgb,var(--crit) 40%,transparent);border-radius:4px;padding:2px 7px}
.spec{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.spec-h{font-family:var(--mono);font-size:11px;color:var(--accent);font-weight:600;margin-bottom:10px;letter-spacing:.04em}
.spec-sub{font-family:var(--mono);font-size:9.5px;color:var(--muted);margin:10px 0 5px;text-transform:uppercase;letter-spacing:.08em}
.chip{display:inline-block;background:var(--panel2);border:1px solid var(--line);color:var(--tx);border-radius:5px;
  padding:2px 8px;margin:2px 4px 2px 0;font-family:var(--mono);font-size:11.5px}
.chip.none{color:var(--muted)}
.capcmd{margin-top:16px}
.capcmd span{font-family:var(--mono);font-size:9.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;display:block;margin-bottom:5px}
.capcmd code{display:block;padding:11px 13px;white-space:pre-wrap;word-break:break-word;line-height:1.7;font-size:11.5px;color:var(--accent)}
.xmrow{display:flex;gap:11px;flex-wrap:wrap;margin-bottom:14px}
.xm{flex:1;min-width:158px;background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:13px 15px}
.xm-k{display:flex;align-items:center;gap:7px;font-family:var(--mono);font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px}
.xm-k i{width:7px;height:7px;border-radius:50%;background:var(--m);flex:none}
.xm-v{font-family:var(--mono);font-size:23px;font-weight:700;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.xm-v small{font-size:12px;color:var(--muted);font-weight:400;margin:0 2px}
.xm-n{font-size:11.5px;color:var(--muted);margin-top:3px;font-family:var(--mono)}
.evlist{list-style:none;margin:0;padding:0}
.evlist li{display:flex;gap:12px;align-items:baseline;padding:11px 0;border-top:1px solid var(--line);font-size:13.5px}
.modtag{flex:none;font-family:var(--mono);font-size:9.5px;font-weight:700;padding:2px 8px;border-radius:4px;letter-spacing:.06em;
  color:var(--m);background:color-mix(in srgb,var(--m) 14%,transparent);border:1px solid color-mix(in srgb,var(--m) 38%,transparent)}
.payoff .bighead{display:flex;align-items:center;gap:14px;margin-bottom:18px;color:var(--muted);font-size:14px}
.redx{font-family:var(--mono);font-size:42px;font-weight:800;color:var(--good);letter-spacing:-.03em;line-height:1}
.barrow{display:flex;align-items:center;gap:13px;margin:10px 0}
.barlbl{width:250px;flex:none;font-size:12.5px;color:var(--tx)}
.bartrack{flex:1;height:15px;background:var(--track);border-radius:4px;overflow:hidden}
.barfill{display:block;height:100%;border-radius:4px}.barfill.on{background:var(--good)}.barfill.off{background:color-mix(in srgb,var(--muted) 45%,transparent)}
.barval{width:92px;text-align:right;font-family:var(--mono);font-weight:600;font-variant-numeric:tabular-nums}
.barval small{color:var(--muted);font-weight:400;margin-left:2px}
.payoff-note{margin:16px 0 0;font-size:12.5px;color:var(--muted);line-height:1.7}
.payoff-note b{color:var(--tx);font-family:var(--mono)}
.oracle{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:0 20px;margin-bottom:16px}
.oracle summary{cursor:pointer;padding:15px 0;font-family:var(--mono);font-size:12px;letter-spacing:.05em;
  text-transform:uppercase;color:var(--muted);display:flex;justify-content:space-between;align-items:center;list-style:none}
.oracle summary::-webkit-details-marker{display:none}
.verdict-pill{font-size:11px;padding:3px 10px;border-radius:20px}
.verdict-pill.ok{color:var(--good);background:color-mix(in srgb,var(--good) 14%,transparent);border:1px solid color-mix(in srgb,var(--good) 40%,transparent)}
.verdict-pill.bad{color:var(--crit);background:color-mix(in srgb,var(--crit) 14%,transparent)}
.oracle-body{padding:4px 0 18px;display:grid;gap:11px;border-top:1px solid var(--line);margin-top:-1px}
.oracle-body div{display:grid;grid-template-columns:130px 1fr;gap:12px;font-size:13px;align-items:baseline}
.oracle-body span{font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.oracle-body b{color:var(--tx)}.oracle-body code{font-size:11.5px}
footer{text-align:center;color:var(--muted);font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;margin-top:32px;opacity:.7}
@media(max-width:720px){.verdict,.grid2,.spec{grid-template-columns:1fr}.barlbl{width:140px}.v-gauge{display:none}}
@media(prefers-reduced-motion:reduce){.live{animation:none}}
"""

def full_page(res):
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>RCA · {esc(res.get('skill',''))}</title><style>{CSS}</style></head>"
            f"<body>{render(res)}</body></html>")

if __name__ == "__main__":
    res = json.load(open(sys.argv[1]))
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(sys.argv[1])[0]+".html"
    open(out, "w", encoding="utf-8").write(full_page(res))
    print("wrote", out)
