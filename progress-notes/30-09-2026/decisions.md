# 30 September 2026

## Reading the reference papers in full — twelve citation corrections, and a result we did not have

Continuation of yesterday's rule: nothing enters a blueprint until it is measured. Today's
version of it is: **nothing stays cited until the paper has been read.** Eleven of the papers in
`blueprints/REFERENCE-PACK-FOR-KERNEL-TRACE.md` were cited from abstracts. Reading them turned up
twelve problems.

**None of them reached a blueprint or a generated skill.** All were confined to the reference pack
and `DOCS/reading-papers/FUTURE-BLUEPRINT-REFERENCES.md`. No completed run is affected. Summaries
live in `DOCS/reading-papers/sources/<slug>/paper.md`; the index is `table.md`.

### The thing worth keeping — four independent studies measuring the same shortfall

This is now a TL;DR bullet in the reference pack, and it should go in the paper's introduction.

| Source | What is missing |
|---|---|
| **Zhou et al. 2021**, 22 industrial faults | **2 could not be debugged at ANY tooling level**, and both are *environment* faults |
| **Dai et al. 2018**, 156 timeout bugs | **60%** produce no error message, 12% a misleading one |
| **Gunawi et al. 2016**, 597 outages | **59%** have no publicly reported root cause |
| **Ghanavati et al. 2020**, 491 leak issues | **1 of 491** found by static analysis; **63%** only visible at runtime |

Four different failure families, four different methods, one conclusion: **the evidence needed to
diagnose these is not in the code, the logs, or the spans.**

**Why this matters more than the individual numbers.** We had been arguing the kernel modality
from what our own runs show. That is fine but it is our data arguing for our method. These four
are independent, published, and none of them set out to make our point. Zhou's is the strongest
because it is a *failure*: they had distributed trace visualisation and two faults still defeated
them, and their own sentence is *"most fault cases **except those caused by environmental
settings** can benefit from trace visualisation."* The environment is the kernel's layer.

### Blueprint 10's discriminator was published in 2021 and we did not know

Gelle, Ezzati-Jivan & Dagenais, *Electronics* 10(21):2610, §4.3. They cap a Cassandra cpu cgroup
at 1% and read the result out of an LTTng kernel trace:

- requests go from ~5 ms to ~2 s
- `PREEMPTED` dominates the critical path
- preemption recurs **every 100 ms**
- the CPU becomes **underused**
- the deciding event, printed in their Table 5:
  `sched_switch prev_comm=java, prev_tid=7949, prev_state=0, next_comm=swapper/2`

That is our `service-cpu-throttle` discriminator — preempted but **not replaced**, `prev_state=0`
plus `next_comm=swapper` — measured independently four years before we wrote it. **Added as a
supporting row.** They do not name the 100 ms as `cfs_period_us`; we can.

**Decision: cite it as confirmation, not background.** It is the only external evidence in the
pack for a `sched_switch` field-level test we rely on, and it came from an injected fault, not
from reasoning.

### Blueprint 3's "honest gap" is narrower than we recorded

The pack says there is **no peer-reviewed MSR paper focused only on connection-pool exhaustion**.
That is still true, but Zhou's **F5** is a verified industrial instance in a peer-reviewed venue:
a microservice whose **thread pool is shared between two request types**, high load of one
exhausts it, the other fails on timeout. Six days to locate. **Replicated in TrainTicket**, so we
can run it. Noted in the pack rather than deleting the gap claim.

### The twelve corrections

Eight were logged yesterday. Today's four:

| # | Where | What it said | What the paper says |
|---|---|---|---|
| 9 | `FUTURE-BLUEPRINT-REFERENCES.md`, `code_n_plus_one` | Chen 2014 reports N+1 costing "more than an order of magnitude" | **It does not.** That figure (130 s → 2 s) is the *excessive data* pattern in Pet Clinic. **One-by-one processing is -17%** in their micro-benchmark, **+8% to -32%** across Broadleaf, significant in **5 of 10** suites |
| 10 | same file + `meta.yaml`, `resource_abuse` | "Suneja et al., IPDS 2020" | **Karn, Kudva, Huang, Suneja & Elfadel, IEEE TPDS 32(3):674-691, 2021.** Suneja is the *fourth* author; "IPDS" is not the venue; 2020 is the acceptance year |
| 11 | Cross-cutting §8 + blueprint 9 | Zhou et al. "IEEE TSE, 2018/2021" | **TSE 47(2):243-260, 2021.** The repository PDF's 2018 header is a stale draft template |
| 12 | Blueprint 10 (addition, not an error) | no empirical source for the `prev_state=0` / swapper test | Gelle 2021 §4.3 publishes it |

**Correction 9 was load-bearing.** It was the stated reason to expect the N+1 signal to be large
enough to see. Chen's actual numbers say the opposite, and say why: *"when the response time of a
program is small, adding batches will not give much improvement... not all anti-patterns are
worth fixing."* **Schema cardinality and baseline latency decide.**

### What that changes for the `code_*` campaign

**Decision: treat injection strength as an open question for `code_n_plus_one` and
`code_serial_awaits` before reading anything into their results.** This is the `noisy_neighbor`
"KPIs barely move" problem again, and we now have published reason to expect it:

- **Chen 2014**: the same anti-pattern ranges +8% to -32% depending on schema shape.
- **DrAsync (Turcotte et al., ICSE 2022)**: refactoring **every** executed instance in two whole
  projects removed ~1.1K and ~1.2K runtime promises and changed test-suite run time **not at all,
  twice**. Their two good numbers (16.4%, 36.1%) are hand-picked fragments, and the larger one
  involved copying a **7.8 GB directory**. Sock Shop's front-end awaits are short local HTTP
  calls.

**But their failure to measure it is an argument for our modality, and it is the sharpest one in
the set.** DrAsync's stated reason is that the eliminated promise lifetimes hide inside a longer
wait. That is a **wall-clock** problem. Serial awaits and `Promise.all` issue **the same number**
of round trips — the difference is **overlap**, whether two requests are ever in flight at once.
That is readable off socket-event timestamps and invisible to every method in their paper.

Same shape for `code_n_plus_one`: Chen measures response time, we count round trips, and a count
survives noise a duration does not.

**Three discriminators fell out of the reading and are now recorded as hypotheses, not findings:**

| Pair | Separator |
|---|---|
| `code_n_plus_one` vs `slow_query` | **many small round-trips** vs **one long one** |
| `code_n_plus_one` vs eager over-fetch | many small vs **few with huge payloads** (Yang 2018) |
| `code_event_loop_block` vs `svc_cpu_cap` | **one thread busy on-CPU** vs **nobody running, CPU idle, 100 ms period** |

The third is half-confirmed already — Gelle publishes the throttling side.

### One thing to check in a recipe before we cite a paper for it

Karn et al. detect cryptomining from **which syscalls**, not CPU share, because *"CPU usage is a
good first-order metric"* that false-alarms on legitimately busy workloads. That is our coverage
sweep's `resource_abuse` problem stated by someone else, and it looked like a rescue.

**It may not be.** Their miners are real binaries doing real work — pool network I/O, file writes,
timers — which is where the 12 distinctive syscalls come from. **If our `resource_abuse` recipe
is a bare spin loop, it may emit no distinctive syscalls at all**, and their method does not
apply. Noted in the future-references doc as a precondition on the citation. Their own data also
warns against a rate-based discriminator: **Hadoop and Cassandra, both benign, out-emitted 4 of
the 5 named miners.**

### Method notes worth stealing

- **Chen et al.** rank detected anti-patterns by **measured** effect (p-value + Cohen's d), because
  static analysis found 483 of one kind. Our blueprint results tables report detection but never
  rank by how much the fault mattered.
- **DrAsync** separates **static occurrences from executed ones** — 293 found, 30 run. The most
  honest table in the `code_*` set.
- **Karn et al.** compute `Sig_fault = W_fault − W_normal` as a set difference over syscalls. That
  is computable across all 24 of our families at once and would give each blueprint a measured
  discriminative set. Expect it to be small: theirs was **12 of 100, with 88 shared**.
- **Karn et al.** also report a **decision tree beating an LSTM by 18 points at 1/500 the training
  time** on syscall data. Useful counterweight to Kohyarnejadfard's LSTM, and evidence that our
  rule-based blueprints are not a compromise.

### State

**38 of 50 papers summarised** (33 by me, 5 by the user). 12 left, listed at the bottom of
`table.md`. The Salesforce connection-pool patent still needs OCR — 21 pages of scanned images,
no text layer; the user will supply screenshots.
