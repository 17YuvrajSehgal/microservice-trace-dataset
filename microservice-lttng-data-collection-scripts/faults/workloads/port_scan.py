#!/usr/bin/env python3
"""Port scan of our own test stack: one source tries every port of every peer.

WHAT THIS IS AND IS NOT. A benign simulation on our own isolated VM, against our own containers
only (the addresses are passed in by the recipe). It opens a TCP connection, records whether the
port was open, refused or silent, and closes it. It sends no data. What it reproduces is the
shape a scan has in a kernel trace: one source, many destinations and ports, almost all refused.

    python3 port_scan.py <ip,ip,...> [first_port=1] [last_port=1024] [connects_per_second=200]
Prints one status line every 10 s. Stops on SIGTERM.
"""
import errno
import select
import signal
import socket
import sys
import time

ips = [x for x in sys.argv[1].split(",") if x]
p0 = int(sys.argv[2]) if len(sys.argv) > 2 else 1
p1 = int(sys.argv[3]) if len(sys.argv) > 3 else 1024
rate = float(sys.argv[4]) if len(sys.argv) > 4 else 200.0
stop = False


def term(*_):
    global stop
    stop = True


signal.signal(signal.SIGTERM, term)
signal.signal(signal.SIGINT, term)
count = {"open": 0, "refused": 0, "silent": 0}
found = set()
pending = {}                                   # socket -> (ip, port, deadline)
last = time.time()
sweeps = 0


def settle(block):
    if not pending:
        return
    _, w, _ = select.select([], list(pending), [], block)
    now = time.time()
    for s in list(pending):
        ip, port, dl = pending[s]
        if s in w:
            err = s.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            if err == 0:
                count["open"] += 1
                found.add((ip, port))
            elif err == errno.ECONNREFUSED:
                count["refused"] += 1
            else:
                count["silent"] += 1
        elif now < dl:
            continue
        else:
            count["silent"] += 1
        s.close()
        del pending[s]


while not stop:
    for port in range(p0, p1 + 1):
        for ip in ips:
            if stop:
                break
            t0 = time.time()
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setblocking(False)
            s.connect_ex((ip, port))
            pending[s] = (ip, port, t0 + 0.5)
            settle(0)
            if time.time() - last >= 10:
                print(f"{time.strftime('%H:%M:%S')} sweeps {sweeps}, tried {sum(count.values())}: open {count['open']}, "
                      f"refused {count['refused']}, silent {count['silent']}; open ports found: {len(found)}", flush=True)
                last = time.time()
            time.sleep(max(0.0, 1.0 / rate - (time.time() - t0)))
        if stop:
            break
    sweeps += 1
settle(0.5)
for s in pending:
    s.close()
print(f"stopped: sweeps {sweeps}, tried {sum(count.values())}: open {count['open']}, refused {count['refused']}, "
      f"silent {count['silent']}; open ports found: {sorted(found)[:40]}", flush=True)
