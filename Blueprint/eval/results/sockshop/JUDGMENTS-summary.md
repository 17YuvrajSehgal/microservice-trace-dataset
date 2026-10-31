# Sock Shop — by-hand judgment summary (see ../../JUDGING.md)

All Sock Shop faults are `verification_status=confirmed` (cpu 8/8, noisy 8/8, slow_db 11/11,
net 5/5 — they measurably bit). Grading is conservative: "other"/"normal"/"unknown" on a real
fault = MISS; naming the aggressor/proxy/DB-peer that the recipe actually used = correct WHERE.

| blueprint | DETECTED | detail |
|---|---|---|
| svc_cpu_cap | **6/8** | r1,r2,r4,subtle_r1,r2,r3 = cpu_throttling on java(carts) pid_ns 4026532538, windows match. r3,r5 named java+right window but hedged fault_type="other" → MISS. |
| noisy_neighbor | **7/8** | r1,r2,r4,r5,subtle_r1,r2,r3 = noisy_neighbor, named aggressor `stress-ng-cpu`, windows match. r3 said normal → MISS. (host scope: naming aggressor is correct, no victim service exists.) |
| slow_db | **8/11** | see slow_db/JUDGMENTS.md. db_latency via toxiproxy/mysqld, incl. 2/3 subtle-60ms. 2 misses are short "burst"; 1 partial. |
| svc_net | **5/5** | service_network on java(carts) pid_ns 4026532538, all 5 windows match (netem 150ms+4% on carts eth0). |
| svc_mem_cap | **8/8 DET** (v1 blueprint 3/8) | **now evaluable** — re-collected w/ memcg 29-30 Oct, eval 31 Oct (direct OpenAI, separate run from the 4 above). v1 blueprint 3/8 → audit-fixed v2 blueprint **8/8** (aggr 5/5, subtle 3/3); reclaim on carts pid_ns 4026532540. See `JUDGMENTS-svc_mem_cap.md`. |

**Total on the 4 evaluable blueprints: 26/32 = 81% DETECTED**, with correct localization, all on
confirmed-biting faults. `java in pid_ns 4026532538` is carts (the only Java service, and the
agent lands on the same pid_ns for both the carts cpu-cap and the carts net fault).

**svc_mem_cap is now the 5th evaluable blueprint** (8/8 DET after its own blueprint audit; v1 was
3/8), kept separate from this 26/32 total because it is a different run — the 29-30 Oct memcg
re-collection, scored 31 Oct via direct OpenAI, while the four above are the earlier OpenRouter v2
pass. (carts is a different pid_ns there — 4026532540 — because it is a fresh collection, i.e. a new
container start.)

Note vs score.py: it reported cpu 5, noisy 0 (pre-fix), slow_db 1, net 5. The gaps were
WHERE-string rigidity (it demanded the gt `target_service` and rejected the aggressor/proxy the
agent correctly named) — exactly why we judge by hand now.
