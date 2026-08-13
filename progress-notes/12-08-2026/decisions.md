# Decisions — 12-08-2026

## Team-facing summary consolidated into `summary.md`
Created `summary.md` at repo root: a plain-language, shareable digest of the last two weeks
(29-07 → 12-08) for the team/supervisors. Rationale: the state was spread across `DATASET_GUIDE.md`,
`RESULTS.md`, three `agentic-rca/RESULTS-*.md`, `todolist.md`, and six daily `progress-notes/` —
no single artifact someone outside the daily loop could read.

Scope decisions for the doc:
- Lead with the **three-method comparison** (statistical ~48% / mmbaro 48% / agent 74% Top-1) since
  that is the current headline, and with `slow_db` as the concrete kernel-wins case.
- Include the three *negative/structural* findings as first-class results, not footnotes:
  (A) the two non-LLM methods have complementary blind spots, (B) naive kernel feature-fusion into
  mmbaro changes nothing, (C) trace-only methods floor-out rather than cliff. Together they are the
  three independent arguments for the kernel-reasoning agent.
- Include real dataset snippets (`ground_truth.json`, an L3 digest line, the bundle tree, the
  manifest row) — the team kept asking "what does a run actually look like".
- Carry the operational constraints (login-node-only agent, watchdog chunking, SS L2/CTF2 gap,
  1,395-run sweep budget) into the shared doc, since they shape what anyone can run next.

No new experiments or method changes this session; results unchanged from 11-08.

## Durability audit before GCP funds expire — dataset is SAFE; VM is already gone
Triggered by the funding deadline. Full archive verification (job 2105959, debug node, 16-way
parallel over all 29 `/project` archives → `/scratch/yuvraj17/verify/report.txt`).

**Verdict: every run is intact on Trillium `/project`, including raw kernel L0.**
- TT **49/49 runs**, all with `ground_truth` + `kernel_l1` + `kernel_l3` + spans + L0 channels.
- SS **60 canonical runs** (+ `normal/gate01`, the Phase-0 test run — the only dir flagged `NO_L0`,
  correctly, since it isn't a dataset run). All SS *fault* recipes have gt + L1 + L3.
- Zero runs missing kernel traces. Archive sizes (SS 137 GB / TT 179 GB vs 246/287 GB on-VM) are
  explained by `pigz` compressing the text modalities; the already-gzipped CTF passes through.

**Derived-layer gaps (raw L0 present, so recoverable, but currently absent):** SS `normal` (6 runs),
SS `anomaly_mem` calibration variants (4), SS `lttng_only` overhead runs (4) have **no L1/L3**.

**GCP billing is ALREADY DISABLED** on project `yuvraj-msc` — `gcloud compute instances list` and
`disks list` both fail with "requires billing to be enabled". So the VMs could not be started; any
VM-only artifact is unreachable until billing is restored by the account owner.

**The one VM-only asset:** `~/experiments/overhead_wave2_clean/` + `overhead_wave2/` on the Sock Shop
VM — the raw evidence behind the RQ4 overhead table in `RESULTS.md`. The push script only covered
`$SRC/<recipe>/` + `$HOME/*_metrics` + `$HOME/*_load.csv`, so `experiments/` was never in scope. The
4 `lttng_only/u200_r0*` kernel bundles *are* archived; their load-generator throughput/latency outputs
are not. The overhead *numbers* are already recorded in `RESULTS.md` — what's at risk is the raw
backing artifact, i.e. a reproducibility/reviewer-evidence concern, not a current-results blocker.

**SS kernel L2 no longer depends on the VM** (correction to the 09-08/11-08 framing): the blocker is
**babeltrace ≥2.1 for CTF2**, not the VM. Trillium's module *and* our source build at
`/scratch/yuvraj17/local/bin/babeltrace2` are **both 2.0.4**. Building 2.1+ from source on Trillium
removes the VM dependency entirely for SS L1/L2/L3 derivation.

## SS CTF2 blocker RESOLVED — babeltrace 2.1.2 built on Trillium, reads Sock Shop traces
Confirmed the diagnosis first rather than assuming: extracted one SS kernel `metadata` out of
`sockshop/svc_net.tar.gz` — it begins `\x1e{"type":"preamble","version":2,...}`, i.e. **CTF 2
JSON-text-sequence metadata**, definitively. Babeltrace 2.1 is the release that added CTF 2 decoding
to `source.ctf.fs`.

Built **babeltrace 2.1.2 "Brossard"** from the upstream tarball (job 2106032, debug node, ~90 s):
`./configure --prefix=/scratch/yuvraj17/local-bt21 --disable-debug-info --disable-man-pages`.
Trillium already has everything needed (gcc 12.3, glib 2.76.3, pkg-config 1.8.1); login node has
internet for the download, compute node does the build (login-node watchdog).

**GOTCHA — must override the library path.** `LD_LIBRARY_PATH` already contains
`/scratch/yuvraj17/local/lib` (the old 2.0.4 install), which **shadows the new lib** and makes the
new binary die with `undefined symbol: bt_get_greatest_operative_mip_version_with_restriction`.
Always run it as:
```bash
LD_LIBRARY_PATH=/scratch/yuvraj17/local-bt21/lib:$LD_LIBRARY_PATH \
  /scratch/yuvraj17/local-bt21/bin/babeltrace2 <trace_dir>
```

**Verified on a real SS trace** (`svc_net_aggressive_steady_r3`, extracted + gunzipped to 11 GB):
- old 2.0.4 → `Invalid metadata version found in plain text signature` (the known failure)
- new 2.1.2 → decodes fine (`syscall_entry_statfs`, `sched_waking`, … with pid/tid/procname)

**Unblocks:** SS kernel **L1/L2/L3** derivation for the runs that lack them (`normal` ×6,
`anomaly_mem` calibration ×4, `lttng_only` ×4) and, more importantly, **SS L2 wait-attribution** so
Sock Shop matches Train Ticket for the RQ3 kernel-compensation test. Cost note: each SS run's L0 is
~11 GB decompressed, so derivation is a per-run extract → derive → discard batch job.
