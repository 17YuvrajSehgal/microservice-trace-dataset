#!/usr/bin/env python3
# slow_reader.py - clients that ask for a large answer and read it very slowly.
#
# Each connection has a very small receive buffer, sends one GET and then reads CHUNK bytes
# every INTERVAL seconds. The client's receive window fills up, it advertises a window of zero,
# and the server cannot send the rest of the answer. When an answer is finished the client asks
# again on a new connection.
#
# Usage: slow_reader.py <host> <port> <path> <connections> [interval_s=1.0] [chunk=256]
# Prints one status line every 10 s. Stops on SIGTERM.
import signal
import socket
import sys
import time

host, port, path, n = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
interval = float(sys.argv[5]) if len(sys.argv) > 5 else 1.0
chunk = int(sys.argv[6]) if len(sys.argv) > 6 else 256
REQ = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode()
stop = False


def term(*_):
    global stop
    stop = True


signal.signal(signal.SIGTERM, term)
signal.signal(signal.SIGINT, term)


def connect():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Must be set BEFORE connect: the window scale is fixed in the handshake.
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2048)
        s.settimeout(3)
        s.connect((host, port))
        s.sendall(REQ)
        s.setblocking(False)
        return s
    except OSError:
        return None


socks = [None] * n
opened = finished = got = 0
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
            d = s.recv(chunk)
            if not d:                 # the whole answer was read, or the server gave up
                raise OSError("closed")
            got += len(d)
        except BlockingIOError:
            pass
        except OSError:
            s.close()
            socks[i] = None
            finished += 1
    if time.time() - last >= 10:
        print(f"{time.strftime('%H:%M:%S')} open {sum(x is not None for x in socks)} of {n}, "
              f"opened {opened}, finished or closed {finished}, bytes read {got}", flush=True)
        last = time.time()
    time.sleep(max(0.0, interval - (time.time() - t0)))
for s in socks:
    if s is not None:
        s.close()
print(f"stopped: opened {opened}, finished or closed {finished}, bytes read {got}", flush=True)
