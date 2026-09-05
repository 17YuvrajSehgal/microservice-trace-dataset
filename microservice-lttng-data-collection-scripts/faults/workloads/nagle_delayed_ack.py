#!/usr/bin/env python3
"""Nagle plus delayed ACK: fixed ~40 ms stalls while every resource looks idle.

THE INTERACTION
---------------
Two TCP features that are individually sensible and together pathological:

    Nagle          the sender holds a small write until the previous data is ACKed,
                   to avoid flooding the network with tiny packets
    delayed ACK    the receiver holds the ACK for up to ~40 ms, hoping to piggyback it
                   on a reply

So the sender waits for an ACK that the receiver is deliberately delaying. The result is a
fixed stall - about 40 ms on Linux - on a write-write-read pattern, which is exactly what a
request built from a small header followed by a small body looks like.

WHY IT IS THE HARDEST CASE WE CAN INJECT
----------------------------------------
Every signal we collect says the system is healthy:

    CPU        idle
    disk       idle
    packets    none lost, none retransmitted
    the app    returns 200s, just slowly

There is nothing to blame. An agent looking for a saturated resource will not find one, which
is precisely why Naser wants cases like this: the agent alone should fail and a blueprint
should win.

WHAT THE KERNEL SHOWS
---------------------
The stall is visible as the gap between `net_dev_queue` on the sender and the response, and as
a sendto/recvfrom pair whose duration clusters tightly around 40 ms. Clustering is the tell -
a queue or a slow service gives a spread, this gives a spike at one value.

The control side runs the identical exchange WITH TCP_NODELAY, so the trace contains the
healthy and stalled versions of the same conversation.

    python3 nagle_delayed_ack.py [connections] [requests_per_conn]
"""
import os
import socket
import statistics
import struct
import sys
import threading
import time

CONNS = int(sys.argv[1]) if len(sys.argv) > 1 else 4
REQS = int(sys.argv[2]) if len(sys.argv) > 2 else 100000
PORT = 18099

stop = threading.Event()
lat = {"nagle": [], "nodelay": []}


def server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", PORT))
    s.listen(64)
    while not stop.is_set():
        try:
            c, _ = s.accept()
        except OSError:
            break
        threading.Thread(target=serve_one, args=(c,), daemon=True).start()


def serve_one(c):
    # NOTE: the server does NOT set TCP_NODELAY either, and it reads the header and body in
    # two reads. That is what gives delayed ACK something to delay.
    try:
        while not stop.is_set():
            hdr = c.recv(4)
            if not hdr:
                return
            n = struct.unpack("!I", hdr)[0]
            body = b""
            while len(body) < n:
                chunk = c.recv(n - len(body))
                if not chunk:
                    return
                body += chunk
            c.sendall(b"ok")
    except OSError:
        return
    finally:
        c.close()


def client(nodelay, tag):
    """The classic write-write-read: a small header, then a small body, then wait."""
    try:
        c = socket.create_connection(("127.0.0.1", PORT), timeout=5)
    except OSError as e:
        print(f"  {tag}: connect failed {e}", flush=True)
        return
    if nodelay:
        c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    body = b"x" * 64
    try:
        for _ in range(REQS):
            if stop.is_set():
                break
            t0 = time.perf_counter()
            c.sendall(struct.pack("!I", len(body)))   # write 1: the header
            c.sendall(body)                           # write 2: stalls under Nagle
            c.recv(2)                                 # wait for the reply
            lat[tag].append((time.perf_counter() - t0) * 1000.0)
    except OSError:
        pass
    finally:
        c.close()


def report():
    while not stop.is_set():
        time.sleep(10)
        for tag in ("nagle", "nodelay"):
            v = lat[tag][-500:]
            if v:
                print(f"  {tag:8s} n={len(lat[tag]):6d} median={statistics.median(v):7.2f} ms "
                      f"p95={sorted(v)[int(0.95 * len(v)) - 1]:7.2f} ms", flush=True)


def main():
    print(f"nagle_delayed_ack: {CONNS} stalled + {CONNS} control connections, "
          f"pid {os.getpid()}", flush=True)
    threading.Thread(target=server, daemon=True).start()
    time.sleep(0.5)
    for _ in range(CONNS):
        threading.Thread(target=client, args=(False, "nagle"), daemon=True).start()
        # the control: identical exchange with the interaction disabled, so the trace holds
        # both the stalled and the healthy version of the same conversation
        threading.Thread(target=client, args=(True, "nodelay"), daemon=True).start()
    threading.Thread(target=report, daemon=True).start()
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
