# 22-09-2026 — decisions

Continues 21-09. The 360-run matrix finished at 03:40 and the day's work is what it showed.

## 1. The full matrix: 360/360, 4h 21m, nothing failed

Write-up: `blueprints/docs/Q2-FULL-6-problems.md`. Decisions here.

| problem | WHERE ok | described (v2) |
|---|---|---|
| anomaly_cpu | 60/60 | 79% |
| anomaly_net | 47/60 | 48% |
| noisy_neighbor | 47/60 | 67% |
| slow_db | 21/60 | 68% |
| svc_cpu_cap | **0/60** | 33% |
| svc_net | **0/60** | 37% |

The split is by **scope**: host-wide faults 47-60 of 60, single-service faults zero, twice.

## 2. I nearly published a false modality claim

"Kernel traces cannot localise per-service faults" was the obvious reading of those two zeros.
I checked it against the raw trace before writing it, and it is wrong.

Every event carries the namespaces of the task that produced it:

```
{ pid = 0  tid = 0  procname = "swapper/3"
  cgroup_ns = 4026531835  pid_ns = 4026531836  net_ns = 4026531833 ... }
```

**One `pid_ns` is one container.** 21 per run. `java` alone is five separate containers -
13.3M, 1.74M, 99k, 69k and 20k events. My index kept procname and dropped the namespace, so the
agent saw `java` with no way to tell which, and answered `host`: 56 of 60 on svc_net, 43 on
svc_cpu_cap.

That is the tool, not the modality. The evidence-first rule earned its keep here - the claim
was one paragraph away from being written down.

Index and all three process tools now carry `pid_ns`. Re-run of the two problems is in
`results/q2-ns` with everything else held fixed.

### What the trace still cannot do

There is **no service name anywhere** in a kernel trace, and no mapping to one in the bundle:
`meta/` has container names but no PID list, `ust/` is the Python relay only, `logs/` has names
but no PIDs. So the most precise answer available is "the java in pid_ns 4026533460" - one
container out of 21.

**Decision: that counts as getting WHERE right**, under a new `container` outcome. It is not
"carts", but it is emphatically not "host" either, and marking it wrong would have made the
whole namespace fix invisible - the same silent-zero shape as the empty culprit lists on 21-09.

## 3. The pooled blueprint effect was +0, and that number is meaningless

Pooling six problems that behave nothing alike - three near the ceiling, two on the floor -
averages a real effect against an unrelated zero. Per problem, in percentage points:

| problem | WHERE | window | describe | fault |
|---|---|---|---|---|
| anomaly_cpu | 0 | +3 | +17 | +33 |
| anomaly_net | **+37** | **-37** | -17 | +17 |
| noisy_neighbor | **+23** | +20 | **+44** | +50 |
| slow_db | **+23** | -3 | +29 | +57 |
| svc_cpu_cap | 0 | +27 | +23 | +100 |
| svc_net | 0 | -13 | -6 | +17 |

Three things follow.

- **The blueprint helps where there is headroom.** +37/+23/+23 on the three problems not
  already at ceiling or floor.
- **Its biggest effect is on explaining the mechanism, not naming things**: +44, +29, +23, +17.
  That is what a blueprint is for, and `describe` is not a label match.
- **The fault column is still the tautology** from the first pilot. +100 on svc_cpu_cap means
  the blueprint named the fault. Given-not-chosen; the column measures reading.

**Never report the pooled number.** `q2_arms.py` exists so the per-problem split is the default.

## 4. Open: the anomaly_net window regression

The blueprint makes window-finding **37 points worse** on `anomaly_net`, and it is also the
only problem where the blueprint hurts the description (-17). Large, wrong direction, unexplained.

First guess - the network blueprint sends the agent after packet-level evidence this profile
does not record - is a guess. **Do not write any of this up until it is understood.**

## 5. The window results split cleanly by fault mechanism

| problem | window hits / 60 |
|---|---|
| svc_cpu_cap | 46 |
| noisy_neighbor | 36 |
| svc_net | 22 |
| anomaly_net | 21 |
| slow_db | **1** |

`slow_db` at 1 is the pattern, not an outlier: the process tools find a fault by spotting a
process that arrives or leaves, and a slow database is an existing process answering slowly.

> The WHO tools fixed the fault class whose signature is a new process, and did nothing for the
> class whose signature is timing inside an existing one.

Both halves of that are worth reporting.

## 6. Two scoring bugs caught before spending compute, not after

Both would have hidden the very thing the namespace re-run exists to measure.

- No outcome existed for a container-level answer, so "java in pid_ns 4026533460" would have
  scored `ambiguous` or `wrong`.
- The namespace regex was written through a heredoc that turned `\b` into a literal backspace
  character, so it matched nothing at all.

Caught by running the scorer against six example answers before launching 120 cells. **Third
time heredoc escape mangling has damaged this codebase** - patterns are now built without
literal escapes in the patch text.
