# Next steps (updated 06-08-2026)

## State in one line
**Two complete StrataTrace subjects.** Sock Shop v1 FROZEN (46 runs, `strata-v1-freeze` tag) +
**Train Ticket COMPLETE (49/49, 4 modalities + L0/L1/L3, zero gaps)** on the stopped VM
`strata-tt-collector` (us-east4-c; `/mnt/data` 3 TB data disk + boot disk). See
`06-08-2026/decisions.md` (summary) and `04-08-2026/decisions.md` (detail).

## Critical path (the plan's core deliverable)
1. **Modality-ablation study across BOTH apps** — RCA / anomaly-detection / incident-explanation /
   repair, each with modality subsets, over Sock Shop + Train Ticket. This is what proves the
   dataset's value (`msr-research.md` §10). Now unblocked with two diverse subjects (per-service DB
   vs shared MySQL; DNS vs nacos gateway; small vs 500-700 M-event traces).

## Release packaging (path to citable, plan §8)
2. Datasheet + canonical splits (exclude any borderline/edge runs), Lite/Full tiers, Zenodo DOI,
   GHCR images, finalize `pip install stratatrace`. Do this for BOTH apps.
3. Pull the TT dataset off the VM to durable storage (it currently lives only on the VM's disks) —
   or snapshot the `/mnt/data` disk before it's ever reclaimed.

## Train Ticket cleanups (optional, low priority)
4. Prune the redundant OTel span-logs (~6 GB/run in docker logs — the logging exporter dumps every
   span; redundant with OTLP) for leaner bundles, IF re-collecting.
5. Move `ts-voucher-service` (Python) + `ts-ticket-office-service` (Node) out of `_TT_JAVA` in
   `service_map.py` — non-Java, so agent-injection + `java` svc_comm are no-ops on them.
6. `anomaly_disk` is weak on the SSD box (io_time barely moves) and `anomaly_net`/`anomaly_cpu`
   verify borderline (box already loaded) — fine as documented metrics-weak faults, but note in the
   datasheet.

## Housekeeping
7. Deadlines: MSR 2027 abstract **Nov 5, 2026**, paper **Nov 10**. The ablation study is the
   gating work.
8. `fault_catalog.md` predictions are pre-registered — TT's realized `FAULTS-TT.md` blast radii +
   verdicts are the TT-side record; keep them consistent.
