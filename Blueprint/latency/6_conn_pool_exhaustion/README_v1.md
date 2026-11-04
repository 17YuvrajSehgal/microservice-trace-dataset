# Blueprint 6: connection-pool exhaustion — PARKED (no usable kernel signal yet)

**Status (2026-11-03): not a working blueprint.** The folder keeps `tools/connect_census.py`
(connect() attempts, returns and durations per process, from an earlier session) and this note,
so the next person does not redo the measurement.

## What the fault does

A helper holds authenticated MySQL connections until the server's `max_connections` is reached;
the application's new logins are then refused by MySQL with an error packet ("Too many
connections") after the TCP connection was accepted.

## What the kernel trace shows (measured on `conn_pool_exhaustion_aggressive_steady_r1`)

10 s fault window vs 10 s baseline, the `app` (catalogue) process and its toxiproxy hop:

| | baseline | fault |
|---|---|---|
| `connect()` returns | 854 ok + 610 EINPROGRESS, **0 refused** | 660 ok + 468 EINPROGRESS, **0 refused** |
| connections closed in the window | 1462 | 1127 |
| lifetime p50 / p90 | 0.6 / 4.3 ms | 0.8 / 2.5 ms |
| bytes read per connection, p50 | 52 | 27 |

Because the app connects through toxiproxy (always accepts) and MySQL refuses at the protocol
level, `connect()` never fails. The only kernel-visible difference is a smaller, shorter
connection (the error packet instead of a query answer). That is a weak, driver-specific
signature; calling a fault from it would be guessing, so this blueprint is parked until a run
without the proxy hop or a different driver gives a firm signal.

`connect_census.py` remains useful where the peer refuses at the TCP level (`ECONNREFUSED`,
`ETIMEDOUT`, or connect durations that jump); `12_fd_exhaustion`'s `fd_pressure.py` prints a
`NOTE: CONNECTS REFUSED` line when it sees that.
