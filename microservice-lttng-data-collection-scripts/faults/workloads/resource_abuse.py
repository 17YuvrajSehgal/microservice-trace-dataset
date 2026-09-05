#!/usr/bin/env python3
"""Mining-shaped CPU abuse: a hash loop with a periodic network beacon.

WHAT THIS IS AND IS NOT
-----------------------
This is a BENIGN SIMULATION on our own isolated VM. It computes SHA-256 in a loop and opens a
short TCP connection to a local listener every few seconds. There is no mining, no pool, no
external contact, and no payload of any kind. What it reproduces is the SHAPE that abusive
compute has in a kernel trace, so we can ask whether that shape is separable from ordinary
load.

WHY IT IS NOT JUST ANOTHER noisy_neighbor
-----------------------------------------
`noisy_neighbor` runs stress-ng and is pure CPU burn. This has the same CPU profile and adds
one thing: a REGULAR, SMALL, OUTBOUND connection at a fixed interval - the stratum-style
heartbeat that separates coordinated abuse from a badly-behaved batch job.

So the pair asks a real question: given two workloads that both saturate CPU, can a blueprint
tell "someone is using our machine" from "our own job is heavy"? The answer is either a new
discriminator or an honest limit, and both are results.

    python3 resource_abuse.py [threads] [beacon_interval_s]
"""
import hashlib
import os
import socket
import sys
import threading
import time

THREADS = int(sys.argv[1]) if len(sys.argv) > 1 else 4
BEACON_S = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
BEACON_PORT = 18098

stop = threading.Event()
counts = {"hashes": 0, "beacons": 0}
lock = threading.Lock()


def beacon_sink():
    """A local listener, so the beacon never leaves the machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", BEACON_PORT))
    s.listen(16)
    while not stop.is_set():
        try:
            c, _ = s.accept()
            c.recv(64)
            c.sendall(b"ack")
            c.close()
        except OSError:
            return


def hasher():
    """The CPU profile: tight hashing, almost no syscalls, no I/O."""
    data = os.urandom(64)
    n = 0
    while not stop.is_set():
        for _ in range(5000):
            data = hashlib.sha256(data).digest()
        n += 5000
        with lock:
            counts["hashes"] += 5000


def beacon():
    """The distinguishing feature: small, regular, outbound - like a pool heartbeat."""
    while not stop.is_set():
        time.sleep(BEACON_S)
        try:
            c = socket.create_connection(("127.0.0.1", BEACON_PORT), timeout=2)
            c.sendall(b'{"id":1,"method":"submit"}')
            c.recv(16)
            c.close()
            with lock:
                counts["beacons"] += 1
        except OSError:
            pass


def main():
    print(f"resource_abuse: {THREADS} hash threads, beacon every {BEACON_S}s "
          f"(local sink, nothing leaves the host), pid {os.getpid()}", flush=True)
    threading.Thread(target=beacon_sink, daemon=True).start()
    time.sleep(0.3)
    for _ in range(THREADS):
        threading.Thread(target=hasher, daemon=True).start()
    threading.Thread(target=beacon, daemon=True).start()
    try:
        while True:
            time.sleep(10)
            print(f"  hashes {counts['hashes']:,}  beacons {counts['beacons']}", flush=True)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
