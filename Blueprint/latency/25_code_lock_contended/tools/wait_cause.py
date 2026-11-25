#!/usr/bin/env python3
# wait_cause.py - the second step after inside_wait.py: is there another explanation for the
# requests that wait inside a service?
#
# inside_wait.py answers WHERE requests wait. It is true for many faults: on the sweep of
# 25-11-2026 (347 runs) it named a service in 13 fault families besides the two lock families.
# This script reads the outputs of three tools run on the SAME pair of slices and rules out the
# causes those tools can see:
#
#   1. a service that has stopped answering       unanswered.py says SERVICE DOES NOT ANSWER
#   2. packets waiting at a network interface     dev_delay.py says PACKETS WAIT AT THE SENDER'S INTERFACE
#   3. its threads waiting for a core             the inside_wait verdict: CPU wait at or above MIN_CPU_WAIT
#   4. one busy thread doing all the work         the inside_wait verdict: it uses about one whole core
#
# What is left is a wait inside the service that nothing above explains: a lock, a pool, an
# internal queue - or a delay built into that program (see the limits in the blueprint).
#
# Usage:
#   python3 wait_cause.py <inside_wait.out> <dev_delay.out> <unanswered.out>
#   python3 wait_cause.py --selftest
import re
import sys

MIN_CPU_WAIT = 0.5     # thread-seconds per second its threads wait for a core
ONE_CORE = (0.9, 1.2)  # "about one whole core": a single-threaded service that is busy
# Where the bars come from: the numbers on the inside_wait verdict lines of the sweep.
# CPU wait: code_lock_contended 0.17-0.25, db_table_lock 0.01, against anomaly_cpu 0.89-0.98,
# cpu_weight 3.6-7.2, svc_cpu_cap 7.1-15.6. Cores: the blocked or busy Node front-end 1.01-1.09,
# against 0.09-0.31 for the two lock families. Chosen AFTER seeing those numbers.

re_iw = re.compile(r'^VERDICT: REQUESTS WAIT INSIDE THE SERVICE: (.+?) \(pid_ns (\d+)\) at (\S+) has ([\d.]+) requests in flight, '
                   r'([\d.]+) of them wait inside it.*?it uses ([\d.]+) cores, ([\d.]+) threads wait for a core, ([\d.]+) of its calls')


def decide(iw_text, dd_text, un_text):
    out = []
    verdicts = [re_iw.match(l) for l in iw_text.split("\n")]
    verdicts = [m for m in verdicts if m]
    if not verdicts:
        return ["VERDICT: NOTHING TO EXPLAIN (inside_wait.py named no service)"]
    silent = [l for l in un_text.split("\n") if l.startswith("VERDICT: SERVICE DOES NOT ANSWER:")]
    queue = [l for l in dd_text.split("\n") if l.startswith("VERDICT: PACKETS WAIT AT THE SENDER'S INTERFACE:")]
    left = 0
    for m in verdicts:
        name, ns, ip, flight, inside, cores, cwait, down = m.group(1), m.group(2), m.group(3), *[float(x) for x in m.groups()[3:]]
        who = f"{name} (pid_ns {ns}) at {ip}, {inside:.1f} requests waiting inside"
        if silent:
            out.append(f"EXPLAINED: {who} - a service has stopped answering ({len(silent)} verdict line(s) of unanswered.py); follow that")
        elif queue:
            out.append(f"EXPLAINED: {who} - packets wait at a network interface ({len(queue)} verdict line(s) of dev_delay.py); follow that")
        elif cwait >= MIN_CPU_WAIT:
            out.append(f"EXPLAINED: {who} - its threads wait for a core ({cwait:.2f} thread-seconds per second): a CPU limit, a low CPU weight or a busy host")
        elif ONE_CORE[0] <= cores <= ONE_CORE[1]:
            out.append(f"EXPLAINED: {who} - it uses about one whole core ({cores:.2f}): one busy thread does all its work (a blocked or overloaded event loop)")
        else:
            out.append(f"VERDICT: REQUESTS WAIT INSIDE THE SERVICE AND NOTHING ELSE EXPLAINS IT: {who}; it uses {cores:.2f} cores, its threads wait "
                       f"{cwait:.2f} thread-seconds per second for a core, no interface queue, every service answers - a lock, a pool or an internal queue in that program")
            left += 1
    if not left:
        out.append("VERDICT: THE WAIT IS EXPLAINED BY ANOTHER CAUSE (see the lines above)")
    return out


def selftest():
    iw = ("VERDICT: REQUESTS WAIT INSIDE THE SERVICE: app (pid_ns 5) at 10.0.0.5 has 9.4 requests in flight, 5.4 of them wait inside it, "
          "0.59 in the baseline: it uses 0.30 cores, 0.17 threads wait for a core, 3.60 of its calls are waiting for a dependency; answers take 31.0 ms")
    quiet_dd = "VERDICT: NO PACKETS WAITING AT A SENDER'S INTERFACE (longest: p95 0.02 ms)"
    quiet_un = "VERDICT: NO SERVICE THAT DOES NOT ANSWER (most: 0 silent)"
    out = "\n".join(decide(iw, quiet_dd, quiet_un))
    assert "NOTHING ELSE EXPLAINS IT: app (pid_ns 5) at 10.0.0.5, 5.4 requests waiting inside" in out and out.count("VERDICT") == 1, out
    out = "\n".join(decide(iw, "VERDICT: PACKETS WAIT AT THE SENDER'S INTERFACE: app (pid_ns 5) at 10.0.0.5: 900 packets", quiet_un))
    assert "EXPLAINED: app (pid_ns 5) at 10.0.0.5, 5.4 requests waiting inside - packets wait at a network interface" in out, out
    assert "VERDICT: THE WAIT IS EXPLAINED BY ANOTHER CAUSE" in out, out
    out = "\n".join(decide(iw.replace("0.17 threads", "7.05 threads"), quiet_dd, quiet_un))
    assert "its threads wait for a core (7.05" in out, out
    out = "\n".join(decide(iw.replace("0.30 cores", "1.02 cores"), quiet_dd, quiet_un))
    assert "about one whole core (1.02)" in out, out
    assert "NOTHING TO EXPLAIN" in "\n".join(decide("VERDICT: NO REQUESTS WAITING INSIDE A SERVICE (most: 0.2)", quiet_dd, quiet_un))
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if len(sys.argv) < 4:
        print("usage: wait_cause.py <inside_wait.out> <dev_delay.out> <unanswered.out>", file=sys.stderr)
        sys.exit(1)
    texts = [open(p, errors="replace").read() for p in sys.argv[1:4]]
    print("\n".join(decide(*texts)))
