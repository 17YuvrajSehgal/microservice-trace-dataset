#!/usr/bin/env python3
# sampler.py - the v4 "metrics": one row per second for the program (and the host), from /proc.
#
#   sampler.py <pid>   > metrics.csv
#
# Columns: time, program CPU (cores), threads, threads running / sleeping / in D-state, open
# descriptors, resident memory (MB), voluntary and involuntary context switches per second, host
# CPU busy (cores), host load average. The program's numbers include all its threads.
import os
import sys
import time

pid = sys.argv[1]
HZ = os.sysconf("SC_CLK_TCK")


def proc_cpu():
    with open(f"/proc/{pid}/stat") as f:
        v = f.read().rsplit(")", 1)[1].split()
    return (int(v[11]) + int(v[12])) / HZ


def tasks():
    states = {"R": 0, "S": 0, "D": 0}
    vol = inv = 0
    for t in os.listdir(f"/proc/{pid}/task"):
        try:
            with open(f"/proc/{pid}/task/{t}/stat") as f:
                s = f.read().rsplit(")", 1)[1].split()[0]
            states[s if s in states else "S"] += 1
            with open(f"/proc/{pid}/task/{t}/status") as f:
                for line in f:
                    if line.startswith("voluntary_ctxt_switches"):
                        vol += int(line.split()[1])
                    elif line.startswith("nonvoluntary_ctxt_switches"):
                        inv += int(line.split()[1])
        except OSError:
            pass
    return states, vol, inv


def rss_mb():
    with open(f"/proc/{pid}/status") as f:
        for line in f:
            if line.startswith("VmRSS"):
                return int(line.split()[1]) / 1024
    return 0.0


def host_busy():
    with open("/proc/stat") as f:
        v = [int(x) for x in f.readline().split()[1:]]
    return sum(v) - v[3] - v[4], sum(v)


print("utc,cpu_cores,threads,running,sleeping,dstate,fds,rss_mb,vol_cs_per_s,invol_cs_per_s,host_busy_cores,load1", flush=True)
ncpu = os.cpu_count()
last = None
while True:
    try:
        t = time.time()
        c = proc_cpu()
        st, vol, inv = tasks()
        fds = len(os.listdir(f"/proc/{pid}/fd"))
        hb, ht = host_busy()
        with open("/proc/loadavg") as f:
            load1 = f.read().split()[0]
        if last:
            dt = t - last[0]
            print(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t))},{(c - last[1]) / dt:.3f},{sum(st.values())},{st['R']},{st['S']},"
                  f"{st['D']},{fds},{rss_mb():.1f},{(vol - last[2]) / dt:.0f},{(inv - last[3]) / dt:.0f},"
                  f"{(hb - last[4]) / max(1, ht - last[5]) * ncpu:.2f},{load1}", flush=True)
        last = (t, c, vol, inv, hb, ht)
    except (OSError, ValueError):
        break
    time.sleep(1)
