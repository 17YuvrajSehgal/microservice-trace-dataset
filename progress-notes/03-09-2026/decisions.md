# 03-09-2026 — A3: make kernel analysis faster

Task from the 02-09 meeting: kernel runs take too long. Naser's advice was to move off the
slow babeltrace Python binding to the C library.

## The advice did not apply, but half of it was right

**We were never on the Python binding.** Every script already shells out to the C command
line. So there was nothing to switch.

The other half — *"use a library that reads from CTF, not the text"* — is right, and now has
a number. Measured on a real L0 trace (14 GB decompressed, 258M events, SS anomaly_cpu r1):

| One full pass | Time |
|---|---|
| decode only (`-o dummy`) | **101 s** |
| decode **+ format as text** (what we do) | **361 s** |

**72% of a pass is spent formatting text that Python then throws away.** Same ratio on a
second, older trace, so it is not a property of one file.

## The bigger waste was structural, not the text

Ten scripts each opened their **own** babeltrace over the same file, and each scans two
windows. The seven-script blueprint battery is **14 decodes of one trace**.

All ten declare identical windows (baseline 55 s, incident 60 s — checked), so one
extraction can serve every one of them.

`--begin/--end` does help but does not seek: a 60 s window cost 111 s against 361 s for the
whole trace, i.e. 23% of the events for 31% of the time. It decodes and then discards.

## What we built

- `ctf_extract.py` — one decode per window, fanned out to per-family zstd files
- `ctf_stream.py` — scripts read those when `CTF_CACHE_DIR` is set, else decode as before

Fan-out is free: bare decode 108.9 s, decode + 4-way fan-out **110.1 s**.

| | Time |
|---|---|
| old path, per script | 197 s |
| cache build, once per run | 198 s |
| from cache, per script | 26–34 s |

**Seven-script battery: ~23 min → ~7 min**, and re-analysis of an extracted run is read-only.

Design choice worth keeping: each script keeps **its own grep**, and the family file is a
superset. So a script cannot see one line more or fewer than before, and the speedup is
provable by comparing output rather than by trusting a rewrite. The parsing loops were left
byte-identical; only construction and teardown moved.

## Three bugs, all silent

Every one produced a plausible wrong answer rather than a crash.

1. **No `TZ=UTC` in the extractor.** babeltrace prints *and interprets* `--begin/--end` in
   the local zone; our traces are UTC. A 22:43 UTC window was read as 22:43 EDT, four hours
   outside the trace. Every family file came out as a **valid but empty 13-byte zstd frame**,
   and the scripts then "succeeded" in 0.08 s with empty results.
   Guard added: refuse to publish when every family is under 1 KB, and name the timezone.

2. **`tee >(a) >(b)` does not wait.** Bash returns when `tee` exits and never waits for
   process substitutions, so we renamed `.part` into place while `grep | zstd` were still
   flushing. Replaced with explicit FIFOs and a real `wait` on each consumer PID.

3. **Reading `kernel/kernel/` at all.** Those streams are **gzipped** and babeltrace cannot
   read them; the readable copy is `ctf/`, which is 14 GB, not the 2.2 GB the compressed
   directory reports. 93 of these are expanded on scratch, about 1.3 TB.

## The finding that outlasts the speedup: our output was never reproducible

`net_loss_signature` disagreed with the cached run on a raw diff. So I ran the same script
twice **on the same path**. It disagreed there too.

| | Result |
|---|---|
| old vs old | UNSTABLE |
| new vs new | UNSTABLE |
| every measured total | identical (57 ifaces, 3,105,878 queued, 2,971 segments) |

Only **row order** moves. Cause: **26 of 28 sorts in `blueprints/` have no tie-breaker** —
e.g. `rows.sort(key=lambda r: -(r["retrans_pct"] or 0))`. On a healthy run nearly every
interface sits at 0, so they all tie and fall back to insertion order, which follows Python's
per-process string hashing.

This predates the cache entirely. It matters on its own terms: a blueprint claims to be a
**re-runnable** investigation, and ours did not produce the same file twice.
`blueprint_decide.py:160` sorts sockets this way and reads the top row, so a tie there could
in principle flip a verdict.

Fixed in the scripts whose equivalence we proved (net_loss ×2, oncpu_share,
endpoint_latency). The rest use different row-identity keys and still need it.

## Method note

Raw `diff` was the wrong tool twice over — it cannot tell a reshuffle from a real
disagreement, and it called an empty cache a "difference" without saying it was empty.
`canon_compare.py` now keys rows by identity and compares values, and the verification
counts cache lines against a direct decode instead of inferring completeness from the JSON.

Round 1 taught us that a wrong cache looks fine. Round 2 that a matching diff can be luck.

## What is left

- tie-breakers in the remaining ~22 sorts, `blueprint_decide.py` first
- extract the 93 staged runs once, then the `ctf/` dirs (1.3 TB) can go
- optional next lever: a C sink that skips text formatting entirely — worth up to 3.5x more,
  but only after the shared decode is in routine use
