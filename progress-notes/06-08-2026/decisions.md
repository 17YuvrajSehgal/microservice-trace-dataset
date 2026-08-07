# Decisions — 06-08-2026 — TRAIN TICKET DATASET COMPLETE (49/49)

Milestone note. The blow-by-blow detail (every bug, launch lesson, calibration number) is in
`progress-notes/04-08-2026/decisions.md`; this is the clean, explainable summary of what the
Train Ticket track achieved and where it stands.

## What we set out to do
Add **Train Ticket** (FudanSELab, ~48 running containers, Java Spring Boot microservices) as the
**second app** in the StrataTrace dataset, collected **"the same as Online Boutique / Sock Shop"**
(the first app): the same four modalities (kernel traces, distributed traces, logs, metrics), the
same fault families, the same collection + derivation pipeline. Goal: a diverse second subject so
the modality-ablation study generalizes beyond one system.

## What we delivered — a complete 49-run dataset
**49/49 runs, zero gaps**, each with:
- **4 modalities**: LTTng full-syscall kernel trace, OTLP distributed traces, docker logs, Prometheus/cAdvisor metrics
- The **kernel representation ladder**: L0 (raw CTF, gzipped) + L1 (KPI parquet) + L3 (NL digest)
- **Labels**: per-fault ground truth (target, blast radius, expected winning modality, trace
  visibility, injection window) + a QC verification verdict
- Clean index: `~/tt_dataset_manifest.csv` on the VM

**Matrix**: 6 normal (fault-free) references + 12 fault families × intensities × repeats — CPU/mem
caps, service network latency, dependency outage, host anomalies (cpu/mem/disk/net), noisy
neighbor, slow DB, error storm — matching the Sock Shop campaign structure.

## The headline result (why this matters for the paper)
**The verification verdicts, on their own, tell the "kernel-wins" story.** For each fault we asked
"did a resource metric move enough to confirm the injection?":
- **CONFIRMED (13 runs)** — the faults resource metrics CAN see: memory-cap, disk stress, CPU
  saturation, noisy-neighbor contention.
- **BORDERLINE / UNCONFIRMED (30 runs)** — the faults resource metrics MISS: slow DB (a latency
  toxic — the search hangs 16-28 s but MySQL's CPU barely moves), a frozen dependency (a 30 s
  hang, invisible to metrics), service-CPU throttling, network latency. For these, the signal
  lives in the **kernel** (threads blocked on sockets, cgroup throttling) and the client-side
  latency — exactly the modality the dataset argues for.

So **~half the fault families are metrics-blind on Train Ticket** — a stronger version of the same
finding than Sock Shop, because TT services expose no app-level latency metric at all.

## A genuinely new dataset characteristic: scale
Train Ticket is ~3.4× Sock Shop's container count, and under CPU/disk stress with full-syscall
tracing it produces **500-700 million kernel events per 4-minute run** — far larger than any Sock
Shop trace. This drove the two real engineering problems we solved:
1. **Disk**: a run is ~5-11 GB; 49 runs + the derive didn't fit the 500 GB SSD-quota-capped boot
   disk. Fixed by attaching a **3 TB pd-standard data disk** (a different, un-full quota) — no
   fidelity loss, zero LTTng event drops.
2. **Time**: the batch derive is decode-bound on these huge traces (~55-90 min/run); ran it at
   concurrency 6 after freeing the box, ~13 h total.

## Getting a real system running (the hard part, condensed)
Train Ticket's shipped Docker Compose is broken across every FudanSELab release (MongoDB + no
service discovery + no gateway, but the source wants nacos + MySQL + a gateway). We built a
**coherent shared-MySQL deployment** on a forked branch + overlays, and fixed ~8 real app bugs to
get the booking flow (login → search → book → pay) working end-to-end before any collection — plus
a Toxiproxy on the shared MySQL for the DB faults, matching the Sock Shop rig.

## Status
- **Dataset COMPLETE (49/49), VM STOPPED** (cost halted; data persists on the 3 TB `/mnt/data` +
  boot disk, which fstab-remounts on restart).
- All tooling committed + pushed on branch `agentic-tracing`; TT fork branch `stratatrace` pinned
  as a submodule. Train Ticket now has **full parity with Sock Shop**.
