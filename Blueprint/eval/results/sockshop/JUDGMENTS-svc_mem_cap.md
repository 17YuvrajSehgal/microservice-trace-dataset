# svc_mem_cap × Sock Shop — by-hand judgments (memcg re-collection), v1 → v2 blueprint

Graded against `ground_truth.json` + the recipe (`faults/svc_mem_cap.sh`: `docker update -m M
--memory-swap M` on `carts`, hard cap no swap) per `JUDGING.md`. Model gpt-6-luna via **direct
OpenAI** (`reasoning_effort=none`), matched arm, blueprint `4_svc_mem_cap`.

- **v1** = the original blueprint (run 2026-10-31). **3/8 DETECTED, 2 PARTIAL, 3 MISS.**
- **v2** = after the audit-driven blueprint + tool fixes (commits of 2026-10-31). **8/8 DETECTED.**

**Location check is mechanism-based, not nsmap** (nsmap's CPU correlation mislabelled carts here,
ratios to 16×). The in-window memcg reclaim is `java` in pid_ns 4026532540 = carts (verified by raw
decode: 299 events r1, 236 subtle_r2, 756 subtle_r3; stable 29-30 Oct, stack never restarted). The
agent reports the raw pid_ns; naming 4026532540 = correct carts localization per JUDGING §Location.

## Per-run, v1 → v2

| run | v1 grade | v2 grade | what changed |
|---|---|---|---|
| aggr_r1 | PARTIAL | **DETECTED** | v1 committed memory_limit + carts but self-hedged "unconfirmed" (no re-read ratio). v2 commits (conf 0.78): reclaim-above-baseline is decisive, re-read not required. |
| aggr_r2 | MISS (`other`) | **DETECTED** | v1 saw 3,827 reclaim pairs in carts but said `other` ("no repeated-read ratio"). v2 (conf 0.84): "Java PID…in pid_ns 4026532540…strongly supporting a memory-limit fault in that container." |
| aggr_r3 | DETECTED | **DETECTED** | unchanged (conf 0.66). |
| aggr_r4 | MISS (`other`) | **DETECTED** | v1 read it as "workload teardown / scenario transition". v2 (conf 0.83): "raw kernel reclaim events identify that container, hundreds of memcg reclaim in a 10 s slice." |
| aggr_r5 | PARTIAL | **DETECTED** | v1 found reclaim+kill but "couldn't map PID to pid_ns". v2 (conf 0.84): the tool's new pid_ns column gave the container — "671 memcg reclaim pairs…process exiting during the sample" in pid_ns 4026532540. |
| subtle_r1 | DETECTED | **DETECTED** | unchanged (conf 0.84). |
| subtle_r2 | DETECTED | **DETECTED** | unchanged (conf 0.93). |
| subtle_r3 | MISS (`other`) | **DETECTED** | v1 blamed the user cohort. v2 first pass committed memory_limit but the sampled slice's reclaimer read pid_ns 0 (unreadable) → location unknown; after the tool fix (never report pid_ns 0 as the victim) it localized carts (conf 0.85): "Java in pid_ns 4026532540 repeatedly performs memcg reclaim." |

## Tally

| | DETECTED | PARTIAL | MISS |
|---|---|---|---|
| **v1 (original blueprint)** | 3/8 | 2 | 3 |
| **v2 (fixed blueprint + tool)** | **8/8** | 0 | 0 |

## Why the misses happened (audit) and what fixed them

The agent **found the memcg reclaim in carts in every v1 run** — including the 3 misses. It kept
retreating to `other`/`unconfirmed` because the blueprint forced a signature carts (a JVM) cannot
produce:

1. **Demanded a file-cache re-read storm.** carts' memory is anonymous (JVM heap); under a cap it
   reclaims hard but barely refaults from disk, so reads stay low. v1 Step 5/7 made the re-read
   ratio a gate → "no repeated-read ratio → unconfirmed/other" (r1, r2). **Fix:** re-read ratio is
   the file-cache face only, optional; reclaim-above-baseline is decisive.
2. **Read the cap's cascade as a scenario change.** A hard cap makes the victim stall/die and its
   callers idle → broad activity collapse; v1 called this "workload teardown" (r4, subtle_r3).
   **Fix:** §1.2 trap — the collapse is the cascade; trace it to the reclaiming container.
3. **Intermittent reclaim missed by sampling** (r1, subtle_r3 "no reclaim in sampled slices").
   **Fix:** Step 3 — sample where reclaim concentrates; reclaim in any in-window slice confirms.
4. **Couldn't localize** (r5 "couldn't map PID to pid_ns"; subtle_r3 pid_ns 0). **Fix:**
   `mem_pressure.py` now prints a `VICTIM CONTAINER = pid_ns N` rollup and never reports the
   unreadable pid_ns 0 as the victim.
5. **"rather than force the blueprint conclusion."** v1 Step 7 said "one check doesn't fit →
   unconfirmed." **Fix:** a missing secondary signature classifies the face, it does not overturn
   the reclaim — Step 10 "commit, don't hedge".

All fixes are general mechanism reasoning (leakage-audited: no service name, cap value, pid_ns, or
count appears in the blueprint). They raise detection without enabling false positives — the trigger
is still memcg reclaim above baseline, which only fires on a real cap, so abstention on a no-cap run
is unchanged.

> ⚠️ **Single run per cell = preliminary.** The N-seed run after the freeze gives the citable number.
> The v2 pass used two tool versions (the pid_ns-0 guard was added after the first 7 cells); it only
> affects the pid_ns-0 edge (subtle_r3), so the 8/8 is on a consistent decision rule.
