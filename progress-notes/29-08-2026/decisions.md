# Decisions — 2026-08-29

Branch `blueprints`. Phase 1 = kernel traces only.
Full detail in `blueprints/docs/FINDINGS-phase1.md` (findings F1–F10).

## The problem we found first, and why it mattered

Every evidence pack we had came from the two families the blueprints fire on. So a false
positive was **structurally impossible** in that test set, and the reported "100% precision"
was a sensitivity number with no negative class.

Measured it properly: **42% false fires on Sock Shop batch 1, 62% on batch 2**. A healthy
system was diagnosed as a host fault at 0.80 confidence. That is the number that justified
everything else this session.

## The decision that changed the CPU blueprints

**Runqueue delay is not a discriminator.** It is raised in every CPU-family fault and in
healthy load bursts, and its ordering is *inverted* against severity: host saturation 52×,
cgroup cap 15.7×, the co-tenant fault the blueprint was written from 7.1×, a healthy burst
3.7×. Demoted to corroboration in all three CPU blueprints, with the retraction kept.

**Host CPU utilisation replaced it**, measured to split four families with no overlap. The
attribution comes from `sched_switch` alone — which also means the "who took the CPU" step
moved off metrics and into the kernel trace, keeping it inside phase 1.

Why to trust the numbers: the measurement **recovers the recipe's own injected cap to within
1%** (CPUS=1.0 → 0.988/0.997; CPUS=2.0 → 1.978/2.002), with no knowledge of the recipe.

## The reframe that matters most (Yuvraj's correction)

I was treating this as a classifier that needs one number to work everywhere. **It is not.**
A blueprint is a diagnostic guide. Where a fault looks different on a different architecture,
the job is to **record both pictures**, not average them into one threshold.

So the cross-app "failure" became blueprint content. The blueprints now carry `scenarios`,
and the generator renders them into the skill so the agent actually receives them.

The most useful single scenario we recorded: **on a wide fan-out system a single-service CPU
cap has no host-level signal at all** — utilisation 0.8314 → 0.8316. Not weak, absent. The
blueprint says so and sends the reader straight to cgroup counters, which saves an hour of
looking in the wrong place.

## What transfers between applications and what does not

- **Absolute cores transfer.** The co-tenant newcomer took 0.99–2.00 cores on *both* apps,
  because that number is set by the intruding workload.
- **Percentages do not.** The same fault moved utilisation 0.48→0.65 on one app and
  0.80→0.85 on the other. Train Ticket idles at 0.82, Sock Shop at 0.48.
- **A ceiling is scale-free.** Host saturation (≥0.99) was the only rule needing no
  re-calibration.
- The two apps also run different hardware — 12 CPUs vs 16 — so raw core comparisons need care.

## Two measurement failures worth keeping

**Socket peer attribution failed.** The data is there (full IP/TCP headers), but the naive
version reports a slowed peer on the *no-fault* run too. Three reasons written down: it
measures idleness not latency; the peer key is wrong wherever the process is the server; and
`mysqld:3306` never appears at all because **toxiproxy sits in the datastore path**, so the
kernel-visible peer is the proxy. Kept because knowing the naive version fails is worth as
much as the one that works.

**A −0.000 utilisation turned out to be a midnight bug.** One run of 93 has a fault window
crossing midnight; trace clocks are time-of-day so the span came out as −86,340 s. Corrected
value 0.287. My first fix made it worse — wrapping the end time to "00:00:21" makes babeltrace
reject the window, while "24:00:21" is accepted. Reverted with the measurement written beside
the line. The failure was *silent*, so all four time-windowing scripts carry the fix.

## Where it stands

Sock Shop 89% on covered faults, Train Ticket 79%. Total wrong answers 15 → 13 after the last
threshold split (3 fixed, 1 broken — stated rather than smoothed over).

**The CPU cluster is essentially done.** 11 of the 13 remaining errors belong to the
datastore rule, which was deliberately untouched. The other 2 are `anomaly_mem` reading as
co-tenant contention, which is a genuine family overlap — the memory-stress recipe really
does run a container that takes a core — and cannot be resolved from our kernel data, because
the event census found **no `mm_*` or `kmem_*` tracepoints** in these traces.

Deliberate non-fixes: mild datastore runs (4.4× against a 5× bar) are declined rather than
guessed, and the bar was not lowered to score better.
