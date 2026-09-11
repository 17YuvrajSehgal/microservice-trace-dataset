---
name: fd-exhaustion
version: 1
authored_by: measured across all 303 v2 runs and all 27 fault families, both applications
generated_from: blueprints/fd-exhaustion.json
covers: fd_exhaustion
mutually_exclusive_with: healthy-baseline
---
## When this applies
- some requests fail while others to the same service succeed
- no resource looks saturated
- syscall return values are available from the kernel trace

Do NOT use this blueprint when:
- no syscall is returning EMFILE
- DNS or network latency is raised, which exhausts descriptors as a side effect
- the service is down rather than failing

Cheapest check first: count syscall exits with ret = -24 in the incident window. Zero means this blueprint does not apply; hundreds per second means look upstream first.

## Problem signature
- some requests fail while others on the same service succeed
- errors cluster on new connections, not on established ones
- CPU, memory, disk and network all look normal
- the service stays up - it is failing, not down

Telling it apart from its look-alikes:
- **syscalls returning EMFILE per second, from syscall_exit_* with ret = -24** — this problem: a low but persistent rate - between a fraction of one per second and about nine per second, differing several-fold between deployments. Not this problem: exactly zero in 24 of the 27 families, on both applications.
- **the SAME EMFILE rate, as an upper bound** — this problem: stays below ~9/s. Not this problem: a fault that adds latency to name lookups reaches hundreds per second, and one that adds network latency reaches tens - both far above this fault.

## What to look at first
The signals below are sufficient for this problem; you do not need everything.

- kernel: syscall_exit_accept, syscall_exit_accept4, syscall_exit_socket, syscall_exit_open, syscall_exit_openat

Why this set: MEASURED BASIS. The deciding fact is a syscall RETURN VALUE, not a duration, so the exit events are what matter and the entry events are not needed. These five are where EMFILE actually appears when a service runs out of descriptors under load. Collecting all syscall exits also works and is what our own runs did, but it is 41% of all events for a signal that lives in five of them.

## Investigation blueprint
Each step names the capability it needs. The command shown is the binding resolved for THIS environment; another environment may bind a different tool to the same capability without changing the procedure.

1. stage the stored kernel trace for reading
   run: `bash /scratch/yuvraj17/stratatrace/scripts/extract_l0.sh <app> <family> <run_id>`
   expect: a CTF directory the trace reader can open
2. count failing syscalls by errno and by call, both windows
   run: `python3 blueprints/lib/process_probe.py --ctf <ctf> --gt <window> --out <out>/process.json`
   expect: EMFILE per second in each window, and which syscalls returned it
3. combine into the verdict and its artifacts
   run: `python3 blueprints/lib/blueprint_decide.py --pack <pack.json> --out <out>/verdict.json`
   expect: a verdict naming the refusing syscalls, or an explicit non-fire with the reason

## What to produce
- json: verdict, EMFILE per second, which syscalls returned it, and the total error rate that deliberately did not decide it
- xy_chart: failing syscalls per second by errno, baseline against incident
- text: why some requests fail and others succeed, and how to tell a descriptor cap from an upstream stall that exhausts descriptors as a side effect
- text: find the leak on the error path before raising the limit; raising it alone moves the failure later

## Resolution template
Conclude this problem when ALL of:
- syscalls return EMFILE at between 0.13 and 9.3 per second. The floor is calibrated on campaign-confirmed runs; a weaker descriptor cap can sit below it, so a rate between 0 and 0.13 is inconclusive rather than negative
- the rate is sustained across the incident window rather than a single burst
- DNS and network latency are normal, so descriptors are not being consumed by upstream stalls

Prefer a different explanation when:
- dns-delay — EMFILE is very high - hundreds per second - AND name lookups are slow. Measured, slow lookups produced roughly 170x more EMFILE than a descriptor cap does. The descriptors ran out either way; what differs is why.
- network-path-degradation — EMFILE is raised and retransmission is high. Added network latency makes sockets accumulate the same way slow name lookups do, reaching tens of EMFILE per second.
- healthy-baseline — EMFILE is zero. It is zero in 24 of 27 families on both applications, so its absence is strong evidence.

Root cause is: a service at its file-descriptor limit, identified by the process whose accept or socket calls are returning EMFILE

## When to stop
- Conclude when: syscalls are returning EMFILE at a low sustained rate with no upstream latency to explain it
- Stop and switch: EMFILE in the hundreds per second with slow DNS -> dns-delay; EMFILE raised with heavy retransmission -> network-path-degradation
- Evidence insufficient: syscall exit events were not recorded, so return values are unavailable -> request them and re-run. Do NOT fall back to the total failing-syscall rate: the baseline already runs ~16,000 failing syscalls per second, almost all EAGAIN on non-blocking reads, and EMFILE drowns in it.
- Do not exceed 2 rounds of gathering more evidence before reporting what is missing.

## If you are not confident enough
- Do not report a diagnosis below 0.7 confidence.
- name the unresolved question, pick the ONE additional capability that would settle it, check it against the overhead budget, and request it.
- if the floor is still not met after the allowed rounds, report the best-supported hypothesis, its confidence, and precisely what evidence is missing - never present a guess as a diagnosis
