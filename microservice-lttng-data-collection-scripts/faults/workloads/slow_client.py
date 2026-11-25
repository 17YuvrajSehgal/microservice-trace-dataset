#!/usr/bin/env python3
# slow_client.py - clients that send a request body very slowly.
#
# Each connection sends the headers of a POST with a large Content-Length and then one byte of
# body every INTERVAL seconds. A server that reads the body on a worker thread keeps that thread
# for as long as the client likes. Enough such connections hold every worker thread.
#
# Usage: slow_client.py <host> <port> <path> <connections> [interval_s=1.0]
# Prints one status line every 10 s. Stops on SIGTERM.
import select
import signal
import socket
import sys
import time

host, port, path, n = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
interval = float(sys.argv[5]) if len(sys.argv) > 5 else 1.0
HEAD = (f"POST {path} HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\n"
        f"Content-Length: 1000000\r\nConnection: keep-alive\r\n\r\n").encode()
stop = False


def term(*_):
    global stop
    stop = True


signal.signal(signal.SIGTERM, term)
signal.signal(signal.SIGINT, term)


def connect():
    try:
        s = socket.create_connection((host, port), timeout=3)
        s.sendall(HEAD)
        s.setblocking(False)
        return s
    except OSError:
        return None


socks = [None] * n
opened = closed = sent = 0
last = time.time()
while not stop:
    t0 = time.time()
    for i in range(n):
        s = socks[i]
        if s is None:
            s = socks[i] = connect()
            opened += s is not None
            continue
        try:
            # The server answered or closed: this connection no longer holds a thread.
            if select.select([s], [], [], 0)[0]:
                raise OSError("server answered or closed")
            s.send(b" ")            # leading white space is valid JSON, so the parser keeps waiting
            sent += 1
        except OSError:
            s.close()
            socks[i] = None
            closed += 1
    if time.time() - last >= 10:
        print(f"{time.strftime('%H:%M:%S')} open {sum(x is not None for x in socks)} of {n}, "
              f"opened {opened}, closed by the server {closed}, body bytes sent {sent}", flush=True)
        last = time.time()
    time.sleep(max(0.0, interval - (time.time() - t0)))
for s in socks:
    if s is not None:
        s.close()
print(f"stopped: opened {opened}, closed by the server {closed}, body bytes sent {sent}", flush=True)
