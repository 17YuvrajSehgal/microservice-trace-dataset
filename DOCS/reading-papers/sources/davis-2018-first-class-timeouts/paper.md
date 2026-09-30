# Paper Context: A Sense of Time for JavaScript and Node.js — First-Class Timeouts as a Cure for Event Handler Poisoning (USENIX Security 2018)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> The source for the **`code_event_loop_block`** fault family, which has no blueprint yet. It
> names the failure mode — **Event Handler Poisoning** — and gives the mechanism we need to
> separate that fault from `svc_cpu_cap`. See §8.

---

## 1. Bibliographic info

- **Title:** A Sense of Time for JavaScript and Node.js: First-Class Timeouts as a Cure for
  Event Handler Poisoning
- **Authors:** James C. Davis, Eric R. Williamson, Dongyoon Lee (Virginia Tech)
- **Venue:** 27th USENIX Security Symposium, 15-17 August 2018, Baltimore
- **Open access:** https://www.usenix.org/conference/usenixsecurity18/presentation/davis
- **Prototype:** Node.cure

```bibtex
@inproceedings{davis2018sense,
  title     = {A Sense of Time for {JavaScript} and {Node.js}: First-Class Timeouts as a Cure for Event Handler Poisoning},
  author    = {Davis, James C. and Williamson, Eric R. and Lee, Dongyoon},
  booktitle = {27th USENIX Security Symposium}, year = {2018}
}
```

The same authors' earlier EUROSEC 2017 paper (DOI 10.1145/3065913.3065916) is the original
statement of EHP but is **paywalled**. This one covers the same ground and is open.

---

## 2. One-paragraph summary

The Event-Driven Architecture scales by **multiplexing many clients onto very few threads**.
That is exactly why it breaks: if one callback runs too long, the thread it is on cannot serve
anybody. The authors call this **Event Handler Poisoning (EHP)** and show it is a **denial of
service attack**, not just a performance bug — **35% of the security vulnerabilities reported for
npm modules (403 of 1,132) can be used as an EHP vector**. Their defense is **first-class
timeouts**: make `TimeoutError` a language-level guarantee, the way `OutOfBoundsError` is for
buffer overflow, so no event handler can block indefinitely. Their Node.cure prototype stops
**all known EHP attacks** at **0-24% overhead on real applications**.

---

## 3. The architecture, and why it is fragile

Node.js has:

- **one single-threaded Event Loop**, and
- **a small Worker Pool** for offloaded work such as file I/O. Node's Worker Pool can hold at
  most **128** workers, but typical sizes are small — **the default is four** — so they assume a
  small pool.

Both together are the **Event Handlers**. A request becomes a **lifeline**: a DAG of callbacks
and tasks partitioned across them.

**The asymmetry that matters:**

> *"A poisoned Event Loop brings the server to a halt, while the throughput of the Worker Pool
> will degrade for each simultaneously poisoned Worker."*

So poisoning **one** Event Loop is total; poisoning the Worker Pool is gradual and needs enough
simultaneous poisoned workers.

**Why the usual defenses do not work here.** In the one-thread-per-client architecture you can
kill and replace a stuck client thread. In the EDA **clients are not isolated on separate
execution resources**, so *"detecting and restarting a blocked Event Loop will break all existing
client connections, resulting in DoS."* The cure would be the disease.

---

## 4. Where the blocking comes from — their taxonomy

Three axes: **which handler** (Event Loop / Worker), **CPU-bound or I/O-bound**, and **which
layer** (language / framework / application).

| | Event Loop, CPU | Event Loop, I/O | Worker, CPU | Worker, I/O |
|---|---|---|---|---|
| **Language** | Regexp, JSON | — | — | — |
| **Framework** | Crypto, zlib | FS | Crypto, zlib | FS, DNS |
| **Application** | `while(1)` | **DB query** | Regexp | **DB query** |

Two attack shapes they demonstrate on a minimal file server:

- **ReDoS** — a catastrophic-backtracking regular expression poisons the Event Loop. **CPU-bound.**
- **ReadDoS** — a directory-traversal bug lets the attacker name a **slow file** (e.g. `/dev/`
  something), poisoning a Worker. **I/O-bound.**

On baseline Node.js **both produce complete DoS, with zero throughput.**

---

## 5. The npm vulnerability study

- Source: a **June 2018 dump of the Snyk.io npm vulnerability database**. They checked CVE and
  the Node Security Platform too and found both were **subsets** of Snyk.
- Classified into 17 categories with regular expressions, tuned until **93%** classified
  automatically; the remaining **7%** marked "Other". Results manually verified.
- **403 of 1,132 vulnerabilities (35%) are usable as an EHP vector.**

Breakdown of the 403:

| Vulnerability class | Count | Why it poisons |
|---|---|---|
| **Directory Traversal** | **266** | arbitrary file reads → ReadDoS on the Event Loop or Worker Pool |
| **Denial of Service** | **121** | poison the Event Loop — **115 are ReDoS**, 11 are infinite loops or worst-case algorithms |
| Arbitrary File Write | 11 | write to a slow file |

They also cite Staicu and Pradel showing ReDoS in popular npm modules is exploitable for EHP
against **hundreds of sites in the Alexa Top Million**.

---

## 6. The defense

**First-class timeouts.** Build `TimeoutError` into the framework so that no event handler can
block, non-destructively. Their argument for why it has to be first class:

- **Per-API timeouts** (e.g. .NET's regex timeout option) are **ad hoc by definition** — you must
  find every dangerous API.
- **Per-process or per-thread timeouts** (OS heartbeat, kill-and-restart) **fail in the EDA**,
  because killing the Event Loop kills every client.

They are honest about the weak point: **choosing the threshold is hard**, and a too-generous
threshold still lets an attacker disrupt legitimate requests. Their suggested mitigation is a
**blacklist** — after a client's request times out, drop its later connections.

They also evaluate **partitioning** (chop long work into small pieces) and reject it: it needs
case-by-case changes, the refactoring cost is **prohibitive**, and **it does not apply to I/O** —
*"an I/O may be just as slow for 1 byte as for 1 MB"*, and **Linux's asynchronous I/O mechanisms
are incomplete for both file I/O and DNS resolution**.

**Node.cure results:** defends against **all known EHP attacks**; overhead **1.3x-7.9x on
micro-benchmarks** but **1.0x-1.24x on real applications** — i.e. **0% to 24%**.

They also audited Node.js for vulnerable APIs and got their **guide on avoiding EHP attacks onto
nodejs.org**.

---

## 7. What kind of paper this is

- A **security paper**: threat model, attack, defense, prototype, evaluation.
- The failure is **adversarial** — an attacker feeding evil input — not an accidental bug.
- No traces, no telemetry, no kernel. The evidence is **vulnerability databases and throughput
  measurements**.
- Node.js specific, though they argue the taxonomy applies to any EDA framework.

---

## 8. What this means for our work

**This gives `code_event_loop_block` a name, a mechanism, and a published frequency.** Our fault
injects synchronous CPU work into a request handler on the Node front-end. That is **EHP,
CPU-bound, at the application layer** — the `while(1)` cell of their Table 1. And it is not a
contrived fault: **121 real npm vulnerabilities do exactly this**, 115 of them by regex.

**The mechanism we actually needed is the Event Loop / Worker Pool split.** Our fault recipe notes
that this *"resembles a CPU quota from the outside"*. Davis et al. explain why it does not have
to, and what to look for:

| | `code_event_loop_block` (EHP) | `svc_cpu_cap` (CFS throttling) |
|---|---|---|
| Is a thread running? | **yes — one thread is busy on-CPU the whole time** | **no — threads are off-CPU** |
| What is the CPU doing? | **busy**, running the poisoned handler | **idle**, `next_comm=swapper` |
| Pattern in time | **one continuous block** for the length of the evil request | **periodic**, on the 100 ms `cfs_period_us` boundary |
| Who is affected | **every client of that process**, including requests that never touch the slow path | the whole cgroup |

**That is a clean discriminator and it uses signals we already have.** One busy thread with idle
peers is the opposite of throttling, where nobody runs and the CPU goes idle. Worth measuring on
our `code_event_loop_block` runs before it goes into a blueprint.

**Their asymmetry predicts a second signature we should check for.** Poisoning the **Event Loop**
is total and instant; poisoning the **Worker Pool** degrades gradually and needs several workers
stuck at once. The Node default pool is **four**. If our injected fault lands on a worker rather
than the loop, the effect should be **partial, not total** — and that would show as four threads
degrading rather than one blocking. Which one our injection actually hits is an empirical
question we have not asked.

**The "everything stalls, including unrelated requests" property is our best WHERE signal.** In
EHP the *symptom* spreads across every request the process handles, but the *cause* is one
handler. This is the same trap as a leak: the requests that fail are not the request that
blocked. Our scorer names a container, which is right here — but we should not claim to have
found the handler.

**One thing to be careful about.** This is a **security paper about an attack**. Our fault is a
**bug** — a developer doing synchronous work by accident. The mechanism is identical, the framing
is not. Cite it for the mechanism and for the 35% prevalence, not for "this is a common
programming mistake" — the paper measures *vulnerabilities*, not mistakes.

**A limit that constrains the whole family.** They note **Linux's asynchronous I/O is incomplete
for file I/O and DNS resolution**. That is why Node offloads to a Worker Pool at all, and it is
why an I/O-bound block is invisible as "blocked on a syscall" from the JavaScript side. From the
kernel side it is perfectly visible — which is a point in our favour and worth saying.

---

## 9. Safe claims

- The EDA multiplexes many clients onto few Event Handlers; **a blocked handler renders the
  server unresponsive**. The authors name this **Event Handler Poisoning**.
- Node.js has **one single-threaded Event Loop** plus a **small Worker Pool** (at most 128, small
  in practice). **A poisoned Event Loop halts the server; a poisoned Worker Pool degrades
  throughput per poisoned worker.**
- **403 of 1,132 (35%) of npm security vulnerabilities in the Snyk.io database (June 2018) can be
  used as an EHP vector** — 266 directory traversal, 121 denial of service (115 of them ReDoS,
  11 infinite loops or worst-case algorithms), 11 arbitrary file write.
- Their classification was automated with regular expressions to **93%** coverage, remainder
  marked "Other", results manually verified. CVE and Node Security Platform were **subsets** of
  Snyk.
- Vulnerable APIs span **language (regexp, JSON), framework (crypto, zlib, FS, DNS), and
  application (`while(1)`, DB query)**, and are either CPU-bound or I/O-bound, on either the Event
  Loop or a Worker.
- On baseline Node.js, both a **ReDoS** (CPU-bound) and a **ReadDoS** (I/O-bound) attack produce
  **complete DoS with zero throughput**.
- **Killing and restarting a blocked Event Loop is not a fix** — it breaks every existing client
  connection, which is itself a DoS. Per-API timeouts are ad hoc; per-thread timeouts do not
  apply because clients are not isolated.
- **Partitioning long work is rejected**: prohibitive refactoring cost, and it does not apply to
  I/O, because **Linux's asynchronous I/O is incomplete for file I/O and DNS resolution**.
- **Node.cure defends against all known EHP attacks** at **1.0x-1.24x on real applications**
  (1.3x-7.9x on micro-benchmarks).
- The hard part of timeouts is **picking the threshold**; they recommend pairing it with a
  client blacklist.
- Their EHP-avoidance guide is published on **nodejs.org**.

## 10. Do NOT claim

- That this is about accidental performance bugs. It is a **security paper about an attack**, and
  the 35% figure counts **reported vulnerabilities**, not developer mistakes.
- That 35% of npm modules are vulnerable. It is 35% of **reported vulnerabilities in the
  database**.
- That it uses traces or any runtime instrumentation of the OS. It does not.
- That the Worker Pool holds 128 workers in practice. 128 is the maximum; the default is four and
  the paper assumes a small pool.
- That first-class timeouts are deployed. Node.cure is a **prototype**.

## 11. Reusable ideas

- **Name the failure mode.** "Event Handler Poisoning" did more work for this problem than any
  measurement — it let them count 403 instances of it in a database that had never used the term.
- **Make the error first class.** Their `OutOfBoundsError` analogy is the cleanest argument in the
  paper: a guarantee at the language level beats a checklist of dangerous APIs.
- **Say when the obvious fix is itself the failure.** Restarting a blocked Event Loop is a DoS.
  Worth copying into any remediation advice a blueprint gives.
- **One busy thread versus no running thread.** A two-state distinction that separates a blocked
  handler from a throttled cgroup, and it is directly readable from `sched_switch`.
- **Reuse an existing vulnerability database with a new lens.** They did not collect data; they
  re-read Snyk's with one question. Cheap, and it produced the paper's headline number.
