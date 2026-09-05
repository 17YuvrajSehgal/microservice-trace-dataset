#!/usr/bin/env python3
"""Hold open AUTHENTICATED connections to a datastore until it refuses new ones.

WHY OCCUPANCY AND NOT LOAD
--------------------------
This is deliberately NOT a load test. No useful query is sent and nothing is written. The
connections simply exist and are held, so the database keeps answering its existing clients
perfectly well while having no room for new ones.

That is what makes it a good look-alike of `queue_backlog` and a hard case in its own right:
the resource everyone blames - the database - looks healthy on every metric it reports. The
failure is at `connect`, one layer earlier.

It is also the Train Ticket analogue of queue_backlog, which TT cannot run because it has no
message broker (FAULTS-TT.md). Connection-pool exhaustion is the saturation fault both
applications can share.

THE FIRST VERSION HELD RAW TCP SOCKETS AND OCCUPIED NOTHING
-----------------------------------------------------------
It opened a socket, read the server greeting, and called that a held connection. Measured on
the collection VM while it claimed to be holding 400:

    max_connections     151
    Threads_connected     3      <- not 403
    Aborted_connects    750      <- the server threw every one away
    application         HTTP 200
    fresh connection    succeeded

MySQL sends its greeting, waits for an auth packet, and aborts the connection when none
arrives. A pre-auth connection never counts against max_connections. So the fault occupied
nothing at all - and `getpeername()` still succeeded on the locally-open socket, so the
workload cheerfully reported "still holding 400/400", which was false.

It passed the smoke test, because the check read this program's own claim instead of the
server's state. A fault that never happened, labelled as one that did, is the worst outcome
this project has - nothing downstream can detect it.

Two consequences, both applied here:
  1. LOG IN. Only an authenticated connection occupies a slot.
  2. REPORT WHAT THE SERVER SAYS, not what we believe. Every status line below is read out of
     the database with SHOW STATUS, so the evidence comes from the thing being attacked.

    python3 conn_pool_exhaustion.py <host> <port> <connections|auto> [user] [password]
"""
import sys
import time

import pymysql

HOST = sys.argv[1] if len(sys.argv) > 1 else "catalogue-db"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 3306
WANT_ARG = sys.argv[3] if len(sys.argv) > 3 else "auto"
USER = sys.argv[4] if len(sys.argv) > 4 else "root"
PASSWORD = sys.argv[5] if len(sys.argv) > 5 else ""

held = []


def connect(timeout=4):
    return pymysql.connect(host=HOST, port=PORT, user=USER, password=PASSWORD,
                           connect_timeout=timeout, read_timeout=timeout)


def server_status(conn):
    """max_connections, Threads_connected, Aborted_connects - straight from the server."""
    out = {}
    try:
        with conn.cursor() as c:
            c.execute("SHOW VARIABLES LIKE 'max_connections'")
            for k, v in c.fetchall():
                out["max_connections"] = int(v)
            c.execute("SHOW STATUS WHERE Variable_name IN "
                      "('Threads_connected', 'Aborted_connects', 'Max_used_connections')")
            for k, v in c.fetchall():
                out[k] = int(v)
    except Exception as e:                                             # noqa: BLE001
        out["error"] = str(e)[:80]
    return out


def main():
    # A monitor connection, opened FIRST and kept out of the pool being held, so there is always
    # a way to ask the server what it thinks even once it is full.
    try:
        monitor = connect()
    except Exception as e:                                             # noqa: BLE001
        print(f"  ERROR: cannot log in to {HOST}:{PORT} as {USER}: {e}", flush=True)
        print("  Nothing was injected. Check host, port, network and credentials.", flush=True)
        sys.exit(1)

    st = server_status(monitor)
    limit = st.get("max_connections", 151)
    print(f"conn_pool_exhaustion: {HOST}:{PORT} as {USER}; server max_connections={limit}, "
          f"already connected={st.get('Threads_connected', '?')}", flush=True)

    # ADAPTIVE, like fd_exhaustion. A fixed 400 against a server that allows 151 wastes 249
    # doomed attempts; a fixed 400 against a server that allows 1000 exhausts nothing at all.
    # Ask the server what its ceiling is and aim at that.
    if WANT_ARG == "auto":
        want = limit + 20          # deliberately past the ceiling: the refusals are the fault
    elif WANT_ARG.endswith("%"):
        want = max(1, int(limit * float(WANT_ARG[:-1]) / 100.0))
    else:
        want = int(WANT_ARG)

    refused = 0
    first_refusal_at = None
    for _ in range(want):
        try:
            held.append(connect(timeout=3))
        except Exception as e:                                         # noqa: BLE001
            refused += 1
            if first_refusal_at is None:
                first_refusal_at = len(held)
                print(f"  REFUSED after {first_refusal_at} connections: {str(e)[:90]}",
                      flush=True)
            if refused > 30:
                break
            time.sleep(0.05)

    # SATURATED means the SERVER refused, not that we opened a lot of sockets.
    #
    # Measured on Train Ticket: MySQL 8 allows 2000 connections and the holder container's own
    # RLIMIT_NOFILE is 1024, so it topped out at 1020 held / 1221 connected and never reached
    # the ceiling. "1221" is a big number that looks like success and is not - the server had
    # 39% of its capacity free and the application was never squeezed. The recipe raises the
    # holder's own limit now, and this line reports the honest verdict either way.
    st = server_status(monitor)
    saturated = "yes" if refused > 0 else "no"
    print(f"  holding {len(held)} connections, {refused} refusals, saturated={saturated}; "
          f"server reports Threads_connected={st.get('Threads_connected', '?')}/"
          f"{st.get('max_connections', '?')}", flush=True)
    if saturated == "no":
        print(f"  WARNING: the server never refused. It has "
              f"{st.get('max_connections', 0) - st.get('Threads_connected', 0)} slots free, so "
              f"the application is NOT being squeezed. Raise the holder's nofile or CONNS.",
              flush=True)

    if not held:
        # A fault that injected nothing is worse than one that failed loudly, because the run
        # would be labelled as if it had worked.
        print("  ERROR: could not hold ANY connection - wrong host/port/network/credentials?",
              flush=True)
        sys.exit(1)

    try:
        while True:
            time.sleep(10)
            # Prove the connections are still ALIVE by using them, not by asking the local
            # socket whether it thinks it is open. That was the bug.
            alive = 0
            for conn in held:
                try:
                    conn.ping(reconnect=False)
                    alive += 1
                except Exception:                                      # noqa: BLE001
                    pass
            st = server_status(monitor)
            print(f"  still holding {alive}/{len(held)}, saturated={saturated}; "
                  f"server Threads_connected={st.get('Threads_connected', '?')}/"
                  f"{st.get('max_connections', '?')}", flush=True)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
