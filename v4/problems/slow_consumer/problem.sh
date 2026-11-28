# slow_consumer - a consumer that falls behind its producer.
# A producer puts an 8 KB item in an in-process queue every 2 ms; one consumer takes each item and
# works 1 ms on it. With the fault on, the consumer waits 3 ms per item instead (as if blocked on
# something slow): it handles 333 items per second while 500 arrive. The queue and the program's
# memory grow through the fault, and the age of each item at consumption grows with them. After
# the fault the consumer catches up.
CAND="E8 (slow consumer, v4 controlled tier)"
MECH="producer 500 items/s into an in-process queue; the consumer takes 1 ms per item, 3 ms (sleeping) with the fault"
REMEDIATION="make the consumer faster or add consumers; bound the queue so the producer slows down"
LANGS="c go java python node"
SHORT=slowcons
KPI=item_age_ms; KPI_DIR=up; KPI_FACTOR=10
