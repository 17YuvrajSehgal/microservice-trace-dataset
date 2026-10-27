# slow_db × Sock Shop — by-hand judgment (see ../../JUDGING.md)

Injected: toxiproxy adds latency (steady 500±100 ms, subtle 60±20 ms) on the
catalogue→catalogue-db path. Correct answer = db-path latency (slow dependency), located at the
proxy `toxiproxy` or the DB peer `mysqld`. gt `target_service` is literally "catalogue-db", but
the agent naming `toxiproxy` (the injection point) or `mysqld` (the DB) is the right component.

`score.py` said **1/11**; it demanded the exact string "catalogue-db" and marked the agent wrong
for naming toxiproxy/mysqld. By hand: **8 DETECTED, 1 PARTIAL, 2 MISS.**

| run | agent fault / where / when | grade | reason |
|---|---|---|---|
| aggressive_burst_r1 | normal / unknown | MISS | said normal on a real injection |
| aggressive_burst_r2 | other / unknown (saw ~500 ms mysqld gaps) | MISS | had the signature, refused to commit — conservative MISS |
| aggressive_burst_r3 | db_latency / toxiproxy / 06:32:10–20 | DETECTED | mechanism + proxy path + window inside gt |
| aggressive_steady_r1 | db_latency / toxiproxy / 14:37:50–14:40:02 | DETECTED | 0.4–0.5 s gaps, mysqld healthy → path delay. correct |
| aggressive_steady_r2 | db_latency / mysqld (DB peer) / 14:46:07–14:48:07 | DETECTED | named the DB peer, path-delay reasoning, window ✓ |
| aggressive_steady_r3 | db_latency / toxiproxy / 14:54:46–14:56:56 | DETECTED | app+mysqld gap 1 ms→415 ms, window ✓ |
| aggressive_steady_r4 | db_latency / toxiproxy / 15:03:24–15:05:24 | DETECTED | 0.4–0.5 s proxied-path delay, window ✓ |
| aggressive_steady_r5 | db_latency / toxiproxy / 15:11:30–15:13:30 | DETECTED | 0.4–0.5 s pool gaps, window ✓ |
| subtle_steady_r1 (60 ms) | service_network / toxiproxy / 04:11:30–04:13:00 | PARTIAL | found toxiproxy path latency (50 ms) but labeled it network, and hedged |
| subtle_steady_r2 (60 ms) | db_latency / toxiproxy / 04:21:40–04:22:40 | DETECTED | caught the subtle 58–66 ms jump, window ✓ |
| subtle_steady_r3 (60 ms) | db_latency / toxiproxy / 04:32:30–40 | DETECTED | app+mysqld ~60 ms gaps, proxied path, window ✓ |

**DETECTED 8/11** (73%). Both misses are the short "burst" variant; one of them (burst_r2) had
the 500 ms signal but declined to conclude. The blueprint also caught the hard subtle-60 ms case
(2 of 3). Strong, and the agent's path-delay reasoning ("mysqld healthy → delay on the path, not
an overloaded DB") is exactly the slow_db discrimination the blueprint teaches.
