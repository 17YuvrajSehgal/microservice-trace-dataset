# Telling an anti-pattern from an actual problem

13 September 2026. Answers **point 4**: RCA has to say whether the system is slow because
something broke, or because the code is badly written. Both slow it down. They need different
fixes.

---

## The result

| | before | after |
|---|---|---|
| Runs where a blueprint fired and should not | **46 of 156 (29%)** | **19 of 156 (12%)** |
| Runs a blueprint owns and got right | 85 of 116 (73%) | **85 of 116 (73%)** |

**27 false diagnoses removed, none of the correct ones lost.**

---

## The idea that did not work

> An anti-pattern is present in the baseline window too. A fault only appears in the incident
> window.

Sensible, and **untestable on our data**. `code_defect_lib.sh` restarts the container with
`STRATA_BUG` set at the incident boundary, so in our runs the defect is absent from the
baseline exactly like a fault is.

Worth keeping: it may still be the right test on production data, where an anti-pattern really
has been there all along. We just cannot check it here.

---

## What worked, and it was backwards from what I expected

The datastore blueprint was firing on five anti-pattern families. I assumed the anti-patterns
would look *weaker* than a real fault. They look **much stronger**.

| | socket wait, x its own baseline |
|---|---|
| `slow_db` — a genuinely slow dependency, 22 runs | **1.07 – 144** |
| Five code-defect families, 25 runs | **651 – 2462** |

A ceiling at the geometric midpoint, **306x**, keeps 22 of 22 owned runs and excludes 25 of
25 defect runs. 2.13x of margin on both sides.

### Why the mechanism works

**A slow dependency still answers.** The caller keeps doing work, just more slowly, so its
socket wait grows into the tens.

**Broken code in the caller stops the work entirely.** A blocked event loop, a chain of awaits
that no longer overlap, a lock held across I/O — the service stops serving, so its `poll` call
sits parked for most of the window.

Waiting a thousand times longer than normal is not a slower callee. It is a caller that
stopped.

That is a real distinction between an anti-pattern and a fault, and it is measurable from the
kernel alone.

### What else the ceiling caught

It was derived only against the five code families, but it also excluded:

- `dns_delay` — 5 of 5
- `fd_exhaustion` — 5 of 10
- `conn_pool_exhaustion` — 1 of 10

All were false fires too.

---

## The second hole: a missing measurement counted as a pass

The datastore rule read:

```python
answers_slowly = (not net["endpoint_available"] or worst_endpoint_x >= 18.0)
```

So a run with **no endpoint timing at all** passed the check that something is actually
answering slowly. Three false diagnoses came in exactly that way.

It now fails closed. **An unavailable measurement is not evidence of anything.**

This matters more than three runs: endpoint timing is missing in 14 of 20 healthy runs and
5 of 10 in several fault families. A gate that passes when it cannot run is not a gate.

---

## The third thing, and the worst: we were diagnosing our own instrument

`nagle_delayed_ack` fired `host-disk-saturation` in **10 runs out of 10**. A network stall
called a disk flood, every single time, is not a subtle confusion.

The process "arriving on the disk" in all ten runs was **`lttng-consumerd` — our own trace
collector.**

| | disk requests/s gained by the arriving process | who it was |
|---|---|---|
| healthy run | 37 – 66 | `lttng-consumerd` |
| `nagle_delayed_ack` | **945 – 1058** | `lttng-consumerd` |
| the real disk fault | 698 – 2015 | the injected load generator |

The tracer was missing from the infrastructure list, and the disk rule never consulted that
list anyway. So the instrument's own writes cleared the bar and were reported as the fault.

Excluding it removed all 10 false diagnoses and cost no recall — the real disk fault names the
injected load generator in all 10 of its runs, so it is untouched.

**This is an observer-effect bug, and it is worth stating plainly: for one fault family, we
were measuring the measurement.** It was invisible because the rule produced a confident,
well-formed, completely wrong answer.

---

## What is left

19 false fires remain, and they are two known problems, not new ones:

| | |
|---|---|
| `anomaly_mem → service-memory-cap` | 15 runs. This pair was already recorded as inseparable on 8 Sept. Host memory pressure and a container at its memory limit produce the same reclaim signature. |
| `fd_exhaustion → service-memory-cap` | 4 runs. Same rule, same reason. |

Both need the memory-cap rule re-derived against `anomaly_mem`, which is still open.

---

## What went into the blueprints

**`db-latency-dependency-wait`**
- a fourth discriminator: the same socket wait as an upper bound
- a `rule_out` entry naming "a defect in the calling service, not in what it calls"
- `verdict_when` now states both ends of the band, and requires the endpoint measurement to
  actually exist
- `stop_and_switch` rewritten. It used to just name another blueprint. It now says that
  **switching away does not end the investigation** — each alternative names a different cause
  for the same symptom, so the measurement carries across rather than being thrown away.

**`host-disk-saturation`**
- a discriminator on the identity of the flooding process
- a `rule_out` for "nothing — there is no disk fault here"
- `stop_insufficient` now says that measuring the collector is evidence about the measurement,
  not about the system

---

## Method note

My first attempt at this measured "the slowest endpoint" across families and found nothing —
every signal overlapped completely. The reason was that *the slowest endpoint is a different
endpoint in every run*, so it was never comparing like with like.

Looking at what the rule actually measured on the runs it got wrong took ten minutes and
pointed straight at the answer. **Diagnose the rule before inventing a signal.**
