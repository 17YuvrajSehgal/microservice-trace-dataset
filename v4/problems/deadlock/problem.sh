# deadlock - two locks taken in opposite orders.
# Eight workers take lock A, then lock B, do a little work and let go. With the fault on, one more
# thread takes B, then A (the wrong order). It soon meets a worker that holds A and waits for B;
# both wait forever, and every other worker then waits for A. The program stops doing work and
# never recovers (by design: a deadlock does not end when the "fault" is switched off).
CAND="E7 (deadlock, v4 controlled tier)"
MECH="8 workers lock A then B; with the fault one thread locks B then A; a pair waits forever and the rest wait behind it"
REMEDIATION="take the locks in one global order everywhere (or use a timeout and back off)"
LANGS="c go java python node"
SHORT=deadlock
KPI=done; KPI_DIR=down; KPI_FACTOR=5
