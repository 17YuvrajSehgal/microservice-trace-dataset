# Blueprint 33 results (tool only, 25-11-2026, login node)

Fault runs: the 5 v3 `cpu_weight` runs (carts at cpu.weight 10, a 12-process neighbour for the whole run).

| runs | result |
|---|---|
| `cpu_weight`, 5 | 5 of 5: carts (`java`) waits 3.59-7.15 thread-seconds per second for 0.33-0.38 cores (wait per core 10.6-19.8, 2.23-2.43 in the baseline, 4.5-8.9 times); the other containers' wait per core changed 0.7-0.8 times |
| reversed, 5 | quiet in 5 |
| other v3 slices, 15 | quiet |

Not run on the 347 sweep runs yet. The same quantities in the `cpu_confine.py` tables of the
sweep give: `svc_cpu_cap` 3 aggressive runs with wait per core 29-31 (would fire); all 20 normal
runs at most 1.17 with a rise of at most 2.0; `anomaly_cpu` 1.2-1.6. The bars (5 and 4 times)
were set after seeing those numbers.
