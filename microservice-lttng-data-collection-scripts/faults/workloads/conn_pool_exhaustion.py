#!/usr/bin/env python3
"""Hold open connections to a datastore until it refuses new ones.

WHY OCCUPANCY AND NOT LOAD
--------------------------
This is deliberately NOT a load test. No query is sent and nothing is written. The connections
simply exist and are held, so the database keeps answering its existing clients perfectly well
while having no room for new ones.

That is what makes it a good look-alike of `queue_backlog` and a hard case in its own right:
the resource everyone blames - the database - looks healthy on every metric it reports. The
failure is at `connect`, one layer earlier.

It is also the Train Ticket analogue of queue_backlog, which TT cannot run because it has no
message broker (FAULTS-TT.md). Connection-pool exhaustion is the saturation fault both
applications can share.

WHAT THE KERNEL SHOWS
---------------------
    connect()   succeeds N times, then blocks or returns ECONNREFUSED / EAGAIN
    the app     stalls before it sends a single byte

    python3 conn_pool_exhaustion.py <host> <port> <connections>
"""
import socket
import sys
import time

HOST = sys.argv[1] if len(sys.argv) > 1 else "catalogue-db"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 3306
WANT = int(sys.argv[3]) if len(sys.argv) > 3 else 400

held = []


def main():
    print(f"conn_pool_exhaustion: holding up to {WANT} connections to {HOST}:{PORT}",
          flush=True)
    refused = 0
    for i in range(WANT):
        try:
            s = socket.create_connection((HOST, PORT), timeout=3)
            # Read the server greeting so the connection is fully established and counted by
            # the server, not merely half-open in the accept backlog.
            s.settimeout(0.4)
            try:
                s.recv(128)
            except OSError:
                pass
            held.append(s)
        except OSError as e:
            refused += 1
            if refused == 1:
                print(f"  REFUSED after {len(held)} connections: {e}", flush=True)
            if refused > 40:
                break
            time.sleep(0.05)
    print(f"  holding {len(held)} connections, {refused} refusals", flush=True)

    if not held:
        # A fault that injected nothing is worse than one that failed loudly, because the run
        # would be labelled as if it had worked.
        print("  ERROR: could not open ANY connection - wrong host/port/network?", flush=True)
        sys.exit(1)

    try:
        while True:
            time.sleep(10)
            alive = 0
            for s in held:
                try:
                    s.getpeername()
                    alive += 1
                except OSError:
                    pass
            print(f"  still holding {alive}/{len(held)}", flush=True)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
