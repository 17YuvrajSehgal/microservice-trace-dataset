# 6 September 2026 — decisions

## Context

Campaign finished (303 runs). Question on the table: is the data archived, organised, and ready
to move to Trillium as a v2 release?

---

## 1. Checked the archive layout before trusting it, and found a missing modality

The layout itself is uniform on both VMs — 303 bundles under `/mnt/archive/runs/<recipe>/<run_id>/`,
all packaged, nothing left in `~/traces`, CTF gzipped with `.idx` left plain as babeltrace needs.

But counting **every artefact per run**, not just the bundle, turned up a gap: Sock Shop has 169
client-side load CSVs for 169 runs; Train Ticket has **31 for 134**.

**Why this was worth doing rather than assuming.** All 303 bundles had already passed packaging,
checksums and the alignment audit. Nothing failed. The file was simply absent, and no check
counted it. The bundle-level audit cannot see a missing artefact that lives *beside* the bundle.

## 2. The cause was readable, not guessable — so it was read

The `_load.log` of every affected run is **empty**: no traceback, no `[load] N requests`
completion line. All 134 logs were in the archive, so the failure mode came off disk rather than
from reasoning about the code.

Train Ticket's `load_generator.py` wrote its CSV only after `with ThreadPoolExecutor(...) as ex:`
exited, and that block waits for every worker with no timeout. A worker checks the clock only
*between* journeys; a journey is ~5 sequential requests at a 30 s timeout. Under a fault that
blocks requests a worker overshoots by up to ~150 s — long past the point `run_scenario.sh`'s
cleanup trap kills the generator, with every row still in memory.

The distribution confirms it independently: the families that kept their CSV are exactly the ones
whose fault does not block a request (`normal` 10/10, `anomaly_cpu` 5/5, `anomaly_disk` 5/5).

**The methodological point.** The two generators were deliberately built to share a CLI and a CSV
schema so everything downstream would be identical. They were compared on their interface and
never on their teardown. Sock Shop's sets a stop event and bounds its join at 15 s, then always
writes. That single difference cost 77% of one modality on one application.

## 3. Accepted the loss rather than re-collecting — but did not decide it silently

The rows only ever existed in the killed process's memory; nothing on disk can reconstruct them.
Re-collecting 103 Train Ticket runs is ~620 GB and about a day of VM time to recover **one
modality of four**, with the kernel trace, spans, logs and metrics export complete in all 134.

Recorded as CAMPAIGN-ISSUES issue 14 with the cost stated, because whether it is worth it depends
on whether the ablation study needs a client-side view on Train Ticket. That is a research call.

It bites hardest on `anomaly_net`, where the load CSV was the *stated fallback* for a fault with
no metrics signature (issue 5). The inventory claimed that fallback existed on both applications;
it does not exist on Train Ticket, and has been corrected.

## 4. Fixed the generator so it cannot recur, and proved the fix on the failure mode

The write is now a shared function reachable from three paths: normal completion, a bounded
`duration + 20 s` deadline, and a `SIGTERM` handler.

Tested against a host that **accepts connections and never answers** — the actual failure mode,
not a proxy for it. CSV lands at the deadline; the process exits at once rather than hanging for
the request timeout. (`os._exit` after the write: the interpreter's atexit hook joins pool
threads and held the process open an extra 8 s, which is the lingering generator the trap had to
kill.) Re-checked the healthy path still records rows normally.

## 5. Made the check part of the tooling, not a one-off

`campaign_issues.py` now counts the aux files per run. It reports 103 on Train Ticket and 0 on
Sock Shop, matching the manual count exactly. Same reasoning as deriving the issue list from
bundles: a check nobody re-runs is a check that stops being true.

## 6. Three fixes to the transfer script before anything moves

The archive move was added mid-campaign; `push_to_trillium.sh` still assumed v1's layout.

- **`DEST_ROOT` no longer defaults.** It defaulted to `/scratch/yuvraj17/stratatrace/repo`, where
  v1 lives. v2 reuses every recipe name, so the default would have written v2 tarballs over v1's
  with no warning and no way to tell afterwards which release a file came from.
- **`--verify` counted directories.** Each recipe dir now also holds a `<run_id>_metrics/` per
  run, so `ls -d */` returned exactly twice the run count and every recipe would have reported
  `MISMATCH` — a verifier that always cries wolf is worse than none. Now counts
  `meta/runinfo_end.txt`: 169, not 338.
- **The Prometheus snapshot was not shipped at all.** It sits at `/mnt/archive/prometheus`,
  outside `SRC`. It is the continuous record the per-run exports cannot reconstruct, and what the
  outstanding verdicts get re-scored against.

The per-run aux files need no separate archive now — they sit inside `SRC/<recipe>/`, so the
per-recipe tarball already carries them.

## Still open

- **Trillium capacity.** 1.18 TB alongside v1. The two halves were sized against 1 TB archives
  individually, never together. Confirm quota and inodes before pushing; the push is resumable,
  so a quota stop is recoverable, but checking is cheaper.
- **The v2 destination path** is not decided. Deliberately not guessed — the script now refuses
  to run without it.
- 10 Train Ticket verdicts (`slow_db` ×5, `svc_net` ×5) still uncalibrated.
- Offline re-scoring adapter still unwritten; the Prometheus snapshots mean it is no longer
  urgent, but it is what makes verdicts re-derivable without a live Prometheus.
- `fault_catalog.md` pre-registration for the 15 new families was never done.
