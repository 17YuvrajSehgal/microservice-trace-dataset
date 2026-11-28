# lock_contention - one hot lock held too long.
# Sixteen workers take one lock for a short critical section (20 us), then work outside it (1 ms).
# With the fault on, the critical section takes 2 ms: the workers queue for the lock and spend
# most of their time waiting for it. Nothing stops; everything slows down.
CAND="(v3 lock_contention, v4 controlled tier)"
MECH="16 workers share one lock; with the fault each holds it 2 ms instead of 20 us"
REMEDIATION="shorten the critical section, or split the lock (one lock per shard of the data)"
LANGS="c go java python node"
SHORT=lockcont
KPI=wait_avg_ms; KPI_DIR=up; KPI_FACTOR=5
