# Daily Update — StrataTrace (plain-language)

*Covering ~Aug 1–3, 2026. Written to be explainable without deep background.*

## The one-paragraph version

We finished **collecting** the dataset (all the fault experiments we planned), measured how
much our tracing **slows the system down** (it barely does), and then built the **tools that
turn raw, unreadable kernel data into three usable forms** — tables, a "why was it slow"
breakdown, and plain-English summaries — plus a **one-line loader** so anyone can open a run's
data. We tested all of this on real data, hit and fixed a few real bugs, and we're now
re-generating the derived data cleanly across every experiment. The machine turns itself off
when that finishes.

---

## Background in two sentences

We record what happens inside a small shopping web-app ("Sock Shop") while we deliberately
break things (slow disk, memory pressure, network delays, etc.), capturing **four kinds of
data at once**: metrics, logs, request traces, and — the unusual part — **kernel traces**
(what the operating system itself is doing). The goal is a public dataset + tools that let
researchers study *which kind of data best explains each kind of failure*.

---

## What we did, and why

### 1. Finished collecting the data
- We ran the last batch of experiments ("wave-2"): **5 new fault types, 3 repeats each = 15
  runs, and every single one worked** (the fault clearly showed up in the data). Added to the
  earlier 40 runs, the dataset now covers 12 fault families.
- **Why it matters:** these new faults (disk, memory, network — at both the whole-machine and
  single-service level) are the "easily-confused" failures that our research questions are
  specifically about. Without them we couldn't answer the main question.

### 2. Measured the "cost" of our tracing
- A fair concern with kernel tracing is *"doesn't recording everything slow the system down
  and ruin the measurements?"* We measured it properly (with warm-up, repeated runs).
- **Result: kernel tracing costs about 0.5% in throughput and ~13% in tail latency.** Small
  and well-characterized.
- **Why it matters:** this is a number reviewers always ask for, and almost no comparable
  dataset reports it. It's a selling point.

### 3. Built the "representation ladder" — the heart of the tooling
Raw kernel data is enormous and unreadable (one experiment = **300+ million events**). Nobody,
human or AI, can use it directly. So we built three progressively friendlier forms:

| Level | What it is | Analogy |
|---|---|---|
| **L1** | A compact **table** of key numbers per service, per second (syscall counts, latencies, disk/network/memory activity) | A spreadsheet summary of a huge logbook |
| **L2** | A **"why was it slow" breakdown**: of the time a service spent, how much was working vs. waiting-for-CPU vs. blocked-on-disk vs. blocked-on-network | A doctor saying *why* you're tired, not just *that* you are |
| **L3** | **Plain-English summaries** per service: *"carts: reclaim events jumped from 0, syscall latency 4× normal"* | The one-paragraph note a colleague leaves you |

- **Why it matters:** L2 is genuinely unique — no other data source (metrics/logs/traces) can
  tell you *why* a request was slow at the OS level. And L3 is designed to be fed to an AI (a
  language model) — "how should kernel data be shown to an AI?" is an open question we can now
  study. These derivers are a **contribution in the paper**, not just plumbing.

### 4. Built the loader (the "open a run" button)
- One function — `load_run(folder)` — and you get all four data types back as ready-to-use
  tables, plus the ground truth (what we broke and when).
- **Why it matters:** this is what makes the dataset *usable by others*. It's the difference
  between "here's 160 GB of files, good luck" and "here's a pip-installable package."

### 5. Tested everything on real data — and fixed real bugs
Testing on actual runs is where we caught problems that look fine on paper:
- **The tracer-reader was too slow.** Reading a 300-million-event trace the naïve way took
  over an hour and strained the machine. We rewrote it to be **~15× faster** (a big run now
  ~25 min instead of ~4 hours).
- **Java services were being mislabeled.** Our shopping app's Java services start via a small
  shell script that then launches Java as a *separate* process. Our code was only tracking the
  shell, so those services showed **zero activity**. Fixed it to track the whole process
  family — after the fix, the "carts" service correctly showed **241 threads, 99.9% of its
  time blocked on the network** during a network-delay fault (exactly right).
- **Too many "services" from noise.** The raw data mixed our ~13 real services with ~100
  background operating-system processes (Docker, system tools, etc.). We now **fold all that
  background into a single "system" bucket**, so the tables show a clean ~15 services instead
  of ~150.
- **Why it matters:** each of these would have quietly corrupted the study data. Catching them
  on real runs — not just unit tests — is what makes the released dataset trustworthy.

### 6. Re-generating everything cleanly (running now)
- After the fixes, the derived data from earlier test runs was stale, so we're **re-deriving
  L1 + L3 for all 46 real experiments** with the corrected code. (We excluded 4 leftover
  calibration/debug runs that aren't part of the real dataset.)
- Before starting, we ran a **full pre-flight check** — right code version, dependencies,
  disk space, an end-to-end test on one run (confirmed the clean ~16-service output) — so the
  long batch runs on verified footing.
- It's a long job (every trace is huge; ~8–10 hours), running unattended. **The machine shuts
  itself off automatically when it's done**, so we don't pay for idle time.

---

## Honest notes (things worth knowing)
- **These traces are genuinely huge** (100–330 million events each). That's *why* the kernel
  layer is valuable — it sees everything — but it's also why processing takes real time and why
  the reader speed mattered.
- **The cloud machine had intermittent connection hiccups** under heavy processing load. It
  didn't affect the actual work (which runs independently on the machine), just made our
  check-ins occasionally need a retry.
- We chose to **re-do the derivation cleanly rather than patch the dataset after the fact** —
  slower, but the released artifact stays consistent and trustworthy.

## Where we are
- ✅ Data collection: **done** (55 runs, 4 data types, faults confirmed)
- ✅ Overhead measured: **done** (~0.5% throughput / ~13% latency cost)
- ✅ Ladder (L1/L2/L3) + loader: **built and validated on real data**
- 🔄 Clean re-derivation across all runs: **running now**, machine auto-stops when finished
- ⏭️ Next: package the derived data, then the actual study (which data type best explains
  each fault) and the agentic side.
