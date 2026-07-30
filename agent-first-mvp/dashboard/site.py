#!/usr/bin/env python3
"""Build the demo landing page: the skill catalog + the cross-fault benchmark matrix
+ links to each per-fault verdict dashboard. Reuses render.py's design system.

    python site.py <results_dir> <skills_dir> <out_index.html>
"""
import json, os, sys, glob, html
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import render

def esc(s): return html.escape(str(s))

MOD_HUE = {"kernel":"var(--accent)","traces":"var(--good)","metrics":"var(--info)","logs":"var(--warn)"}
def mod_badges(m):
    out = ""
    for part in str(m).replace("+"," ").replace("-only"," only").split():
        hue = next((h for k,h in MOD_HUE.items() if k in part), "var(--muted)")
        out += f'<span class="mb" style="--m:{hue}">{esc(part)}</span>'
    return out

def catalog_row(sk):
    req = sk.get("requirements", {}).get("kernel_lttng", {}) or {}
    scope = (req.get("scope", {}) or {}).get("target_services", [])
    return (f'<tr><td><code>{esc(sk.get("skill"))}</code></td>'
            f'<td>{mod_badges(sk.get("decisive_modality"))}</td>'
            f'<td class="dim">{esc(", ".join(sk.get("problem_triggers", [])[:2]))}…</td>'
            f'<td class="dim">{esc(", ".join(scope) or "—")}</td></tr>')

def bench_row(res):
    v = res.get("verdict", {}); ok = res.get("correct")
    root = v.get("root_cause", "")[:120] + ("…" if len(v.get("root_cause",""))>120 else "")
    red = v.get("reduction_x"); red_txt = f'{red}×' if red else "—"
    return (f'<tr><td class="dim">“{esc(res.get("problem_statement",""))}”</td>'
            f'<td><code>{esc(res.get("skill"))}</code></td>'
            f'<td>{mod_badges(v.get("decisive_modality"))}</td>'
            f'<td>{esc(root)}</td>'
            f'<td class="num">{red_txt}</td>'
            f'<td class="ctr"><span class="pill {"ok" if ok else "bad"}">{"✓" if ok else "✗"}</span></td>'
            f'<td class="ctr"><a class="lnk" href="{esc(res.get("skill"))}.html">open ›</a></td></tr>')

def page(results, skills):
    n = len(results); ncorrect = sum(1 for r in results if r.get("correct"))
    mods = {}
    for r in results:
        mods[r.get("verdict",{}).get("decisive_modality","?")] = mods.get(r.get("verdict",{}).get("decisive_modality","?"),0)+1
    reds = [r["verdict"].get("reduction_x") for r in results if r.get("verdict",{}).get("reduction_x")]
    avg_red = round(sum(reds)/len(reds),1) if reds else None
    cat = "".join(catalog_row(s) for s in skills)
    bench = "".join(bench_row(r) for r in results) or '<tr><td colspan="7" class="dim">No results yet — run the skills.</td></tr>'
    return f"""<main class="wrap">
<header class="top">
  <div class="brand"><span class="live replay"></span>StrataTrace · agent-first observability</div>
  <h1 class="prob">One problem statement in. A different collection plan — and a different decisive modality — out.</h1>
  <div class="meta">A skill compiles a plain-language problem into a scoped, machine-readable collection spec,
  then runs a kernel-deep RCA over four modalities. No incumbent decides <em>what to collect</em> from the problem.</div>
</header>

<section class="statband">
  <div class="stat"><div class="stat-v">{n}</div><div class="stat-k">problems diagnosed</div></div>
  <div class="stat"><div class="stat-v">{ncorrect}/{n}</div><div class="stat-k">match hidden ground truth</div></div>
  <div class="stat"><div class="stat-v">{len(mods)}</div><div class="stat-k">distinct decisive modalities</div></div>
  <div class="stat"><div class="stat-v">{avg_red or "—"}×</div><div class="stat-k">avg less data ingested</div></div>
</section>

<section class="card">
  <h3>Cross-fault benchmark<small>same engine, every fault — the decisive modality differs each time</small></h3>
  <div class="tbl-wrap"><table class="tbl">
    <thead><tr><th>problem</th><th>skill</th><th>decisive modality</th><th>root cause (verdict)</th>
      <th class="num">data ↓</th><th class="ctr">✓GT</th><th class="ctr"></th></tr></thead>
    <tbody>{bench}</tbody></table></div>
</section>

<section class="card">
  <h3>Skill catalog<small>each skill = a collection-aware diagnostic contract</small></h3>
  <div class="tbl-wrap"><table class="tbl">
    <thead><tr><th>skill</th><th>decisive modality</th><th>triggers on</th><th>kernel scope</th></tr></thead>
    <tbody>{cat}</tbody></table></div>
</section>

<footer>StrataTrace · agent-first, collection-aware observability · offline demo site</footer>
</main>"""

EXTRA_CSS = """
.statband{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:16px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px 20px}
.stat-v{font-family:var(--mono);font-size:30px;font-weight:800;letter-spacing:-.02em;color:var(--accent)}
.stat-k{font-size:12px;color:var(--muted);margin-top:2px}
.tbl-wrap{overflow-x:auto}
.tbl{width:100%;border-collapse:collapse;font-size:13px}
.tbl th{text-align:left;font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:.06em;
  color:var(--muted);font-weight:600;padding:0 12px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
.tbl td{padding:12px;border-bottom:1px solid var(--line);vertical-align:top}
.tbl tr:last-child td{border-bottom:0}
.tbl .dim{color:var(--muted)}.tbl .num,.tbl .ctr{text-align:center;font-family:var(--mono);white-space:nowrap}
.mb{display:inline-block;font-family:var(--mono);font-size:10.5px;font-weight:700;padding:2px 7px;margin:1px 3px 1px 0;
  border-radius:4px;color:var(--m);background:color-mix(in srgb,var(--m) 14%,transparent);border:1px solid color-mix(in srgb,var(--m) 38%,transparent)}
.pill{display:inline-block;width:22px;height:22px;line-height:22px;border-radius:50%;font-weight:700}
.pill.ok{color:var(--good);background:color-mix(in srgb,var(--good) 16%,transparent)}
.pill.bad{color:var(--crit);background:color-mix(in srgb,var(--crit) 16%,transparent)}
.lnk{color:var(--accent);text-decoration:none;font-family:var(--mono);font-size:12px;white-space:nowrap}
.lnk:hover{text-decoration:underline}
.statband em,.meta em{color:var(--tx);font-style:normal;font-weight:600}
@media(max-width:720px){.statband{grid-template-columns:1fr 1fr}}
"""

def full_page(results, skills):
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>StrataTrace · agent-first observability</title>"
            f"<style>{render.CSS}{EXTRA_CSS}</style></head><body>{page(results, skills)}</body></html>")

if __name__ == "__main__":
    results_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/mvp_work/results")
    skills_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "..", "skills")
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(results_dir, "index.html")
    order = ["db-slowness-rca","noisy-neighbor-rca","dependency-outage-rca","error-storm-rca","cpu-saturation-rca"]
    results = []
    for p in glob.glob(os.path.join(results_dir, "*.json")):
        try: results.append(json.load(open(p)))
        except Exception: pass
    results.sort(key=lambda r: order.index(r["skill"]) if r.get("skill") in order else 99)
    skills = []
    for p in sorted(glob.glob(os.path.join(skills_dir, "*", "skill.json"))):
        try: skills.append(json.load(open(p)))
        except Exception: pass
    skills.sort(key=lambda s: order.index(s["skill"]) if s.get("skill") in order else 99)
    open(out, "w", encoding="utf-8").write(full_page(results, skills))
    print("wrote", out, "with", len(results), "results,", len(skills), "skills")
