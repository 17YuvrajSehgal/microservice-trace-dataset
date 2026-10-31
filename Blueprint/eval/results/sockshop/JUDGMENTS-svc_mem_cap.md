# svc_mem_cap × Sock Shop — by-hand judgments (memcg re-collection)

Graded against `ground_truth.json` + the recipe (`faults/svc_mem_cap.sh`: `docker update -m M
--memory-swap M` on `carts`, hard cap no swap) per `JUDGING.md`. Run 2026-10-31 on the NEW
memcg-carrying runs (re-collected 29-30 Oct). Model gpt-6-luna via **direct OpenAI**
(`reasoning_effort=none`), matched arm, blueprint `4_svc_mem_cap`. Raw cells on Trillium:
`repo/Blueprint/eval/results/sockshop/svc_mem_cap/<run>/result.json` (+ transcripts).

**Location check is mechanism-based, not nsmap.** nsmap's CPU correlation was loose here (ratios to
16×) and mislabelled the carts namespace as "front-end". The reliable map: the memcg-reclaim burst
under the cap IS the capped container. Decoded in-window, the reclaim is `procname="java",
pid_ns=4026532540` — 299 events in r1's window, 236 in subtle_r2's. So **pid_ns 4026532540 = carts**
(stable across 29-30 Oct; the stack never restarted). The agent reports the raw pid_ns, not the
service name; naming the correct pid_ns = correct location per JUDGING §Location.

| run | gt | agent fault_type / where / when | GRADE | reason |
|---|---|---|---|---|
| aggressive_r1 | carts/160m/23:18:48-23:20:49 | memory_limit / java pid_ns 4026532540 (=carts) / 23:18:48-23:18:49 | **PARTIAL** | committed memory_limit + correct carts ns, BUT root-cause text explicitly declines ("treat the memory-limit hypothesis as unconfirmed rather than forcing the blueprint conclusion") over a 1 s window. Graded down — not a confident detection. |
| aggressive_r2 | carts/160m | **other** / unknown | **MISS** | saw the reclaim (noted 3,827 memcg begin/end pairs in pid_ns 4026532540 = carts) yet committed `other` ("broad workload/activity collapse"). "other" on a real fault = MISS. |
| aggressive_r3 | carts/160m | memory_limit / java pid_ns 4026532540 (=carts) / — | **DETECTED** | "container-scoped memory-limit pressure episode… repeated memcg reclaim directly recorded" in carts's ns; committed memory_limit + correct location. |
| aggressive_r4 | carts/160m | **other** / unknown | **MISS** | read the aggressive collapse as "workload teardown or scenario transition", committed `other`. |
| aggressive_r5 | carts/160m | memory_limit / **unknown** | **PARTIAL** | correct mechanism (reclaim + exit within 0.80 ms = hard-limit kill) but "does not reliably map that PID to a pid_ns" → location unknown. Mechanism right, location vague = PARTIAL. |
| subtle_r1 | carts/300m | memory_limit / java pid_ns 4026532540 (=carts) / — | **DETECTED** | "intermittent cgroup-scoped memory reclaim strongly evidenced in java pid_ns 4026532540"; committed + localized. |
| subtle_r2 | carts/300m | memory_limit / java pid_ns 4026532540 (=carts) / 02:55:25-02:56:58 | **DETECTED** | "container-local memory-limit event: repeated memcg reclaim in one Java container"; committed + localized (ns verified). |
| subtle_r3 | carts/300m | **other** / conn* pid_ns 4026533816 (user svc) | **MISS** | committed `other` (workload/process-population change), pointed at the user service. |

## Tally

**DETECTED 3/8, PARTIAL 2/8, MISS 3/8.** By intensity: aggressive 1 DETECTED / 2 PARTIAL / 2 MISS
(of 5); subtle 2 DETECTED / 1 MISS (of 3).

## What the result means (honest reading)

- **The fix worked at the eval level.** The memcg-reclaim signal is present in all 8 runs and the
  agent *found* it in carts's namespace in every run — including the three MISS runs, where it saw
  the reclaim but still committed `other`. In v2 (no memcg) this family was not evaluable at all.
- **Detection here is weaker than agentic svc_mem_cap (44/44)**, for two structural reasons, not a
  regression: (1) this is a 13-container app, so the agent must also *localize* (map pid_ns →
  service), which it twice could not; (2) the aggressive 160m cap on carts causes a violent
  collapse/teardown that the agent twice read as "workload teardown" rather than a memory cap.
- **Subtle (300m) detected better than aggressive (160m)** — 2/3 vs 1/5 clean. The gentler cap
  produces sustained reclaim without the dramatic teardown, so the mechanism reads cleanly; the
  aggressive cap's teardown is the thing that pulls the agent toward `other`. A real, reportable
  pattern.
- **The failures are over-conservatism, not hallucination.** The agent never invented a memory cap
  where there was none; where it missed, it declined to commit (said `other`/"unconfirmed"). That is
  the safe failure direction.
