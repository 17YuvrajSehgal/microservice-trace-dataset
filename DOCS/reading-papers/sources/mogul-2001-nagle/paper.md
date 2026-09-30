# Paper Context: Rethinking the TCP Nagle Algorithm (ACM SIGCOMM CCR, January 2001)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> The mechanism source for the **`nagle_delayed_ack`** fault family. It gives the deadlock
> precisely, the exact message lengths that trigger it, and a **measured prevalence in a real
> HTTP trace** our pack does not currently use. **It also says our fault family's application
> class is the one that cannot be fixed** — see §7.

---

## 1. Bibliographic info

- **Title:** Rethinking the TCP Nagle Algorithm
- **Authors:** **Jeffrey C. Mogul** (Compaq Western Research Lab), **Greg Minshall** (Redback
  Networks)
- **Venue:** **ACM SIGCOMM Computer Communication Review**, January 2001
- **PDF:** http://ccr.sigcomm.org/archive/2001/jan01/ccr-200101-mogul.pdf

```bibtex
@article{mogul2001rethinking,
  title   = {Rethinking the {TCP} {Nagle} algorithm},
  author  = {Mogul, Jeffrey C. and Minshall, Greg},
  journal = {ACM SIGCOMM Computer Communication Review}, volume = {31}, number = {1}, year = {2001}
}
```

Minshall's name is attached to the modification still shipped in Linux as "Minshall's variant".

---

## 2. One-paragraph summary

Nagle's algorithm stops applications flooding the network with tiny packets, and it works.
**But it interacts with TCP's delayed-ACK policy to produce a temporary deadlock**: the sender
will not send more small data until an ACK arrives, and the receiver will not ACK until more data
arrives. Neither moves until the **delayed-ACK timer** fires — **typically 200 ms, up to 500 ms** —
which adds that delay to operations that should take microseconds. The consequence is that
developers disable Nagle reflexively, **including where it is neither necessary nor wise**,
removing a protection the network needs. The paper classifies which applications should and should
not disable it, and proposes five fixes plus one receiver-side change.

---

## 3. The two algorithms, stated exactly

**Nagle:** if the sender has only a **"small"** amount of data — **less than the connection's
Maximum Segment Size (MSS)** — send it **only if all previously transmitted data has been
acknowledged**.

**Delayed ACK** (from 1982): the receiver **delays acknowledging** so it can piggyback the ACK on
reverse-path data. The specification requires an ACK **at least every second full-sized segment**
(2 × MSS). A timer bounds the delay — **typically 200 ms, allowed up to 500 ms**.

**The assumption delayed ACK makes**, and this is where it breaks: *"the sender is transmitting as
fast as it can ... so we can avoid sending a superfluous ACK packet by simply waiting for the next
data packet."*

### The deadlock

> The Nagle algorithm **prevents the sender from transmitting more data until it receives an
> outstanding ACK**, while the delayed ACK policy **prevents the receiver from transmitting an ACK
> until more data arrives.**

It is **temporary** only because the receiver's timer eventually fires — **at most 500 ms, and BSD
systems cap it at 200 ms**. The paper notes the delays are **especially visible on LANs and
regional networks**, where the RTT is tiny and 200 ms is therefore enormous by comparison.

**Nagle himself analysed his algorithm for deadlock** and did not find this one — the authors
suggest delayed ACKs were not yet widely implemented, or applications did not trigger it.

---

## 4. Exactly when it happens — OF+SFS

Heidemann's observation, which they refine: the deadlock occurs when transmitting a message that
needs an **odd number of full-sized segments plus one additional partial segment** — the authors'
**OF+SFS** (odd full + short final segment).

Their model, assuming buffers large enough to hold the whole message:

| Condition | Result |
|---|---|
| message length strictly between **(2N+1) × MSS** and **(2N+2) × MSS**, for N ≥ 0 | **delayed** |
| message shorter than **2 × MSS** | never delayed |
| message shorter than **MCLBYTES** (the mbuf cluster size) | never delayed |

### The prevalence measurement — this is the number worth having

They applied the model to a **real HTTP trace**:

| | MCLBYTES ignored | MCLBYTES = 4096 | MCLBYTES = 8192 |
|---|---|---|---|
| **MSS = 1460** (Ethernet) | **18.78%** | **18.78%** | **10.05%** |
| MSS = 4312 (FDDI) | 6.71% | 6.71% | 6.71% |

**Between 6.7% and 18.8% of HTTP responses in that trace have a length vulnerable to OF+SFS.**
At the Ethernet MSS of 1460 — the relevant case for us — it is **10-19%.**

---

## 5. Which applications should disable Nagle

Four classes:

| # | Class | Verdict |
|---|---|---|
| 1 | **One-way bulk transfer** (e.g. FTP data) | **Nagle works well.** Proven by a decade of practice |
| 2 | **Telnet-style two-way** | **Nagle works well** (with a caveat about multi-byte keys) |
| 3 | **RPC-style exchanges** — client waits for the response before sending the next request (NNTP client-server mode, traditional SMTP) | **Problematic, but fixable.** Minor modifications give near-optimal performance without abandoning Nagle's intent |
| 4 | **Pipelined exchanges in soft-realtime applications** — client does not wait for a full response before the next request (NFS over TCP, P-HTTP) | **Cannot be fixed** |

Their reason class 4 is unfixable is the sharpest sentence in the paper:

> it is not possible to "fix" the Nagle algorithm for case (4), because **the desired behavior here
> is antithetical to the original intent of the Nagle algorithm**: the application wants a small
> request or response message to be sent **as soon as possible, even if the other end has not
> replied recently.**

They also make the cost of the reflex explicit: disabling Nagle *"can lead to severe network stress
when done by an application with faulty output buffer management"*, and *"many implementors are
forced to disable the Nagle algorithm in circumstances where this should not be required."*

Their advice to application authors: **use appropriate buffering** — the algorithm behaves poorly
*"particularly when the application buffer is smaller than the MSS."*

### The Telnet aside, which is a nice illustration

A multi-byte function key on a 9600-baud terminal delivers bytes ~1 ms apart. The client sends
byte one. The receiver delays its ACK (nowhere near two full segments, nothing to echo yet). The
client sees byte two — and **Nagle defers it, waiting for an ACK that is waiting for data**.
Stevens used this as the canonical reason to disable Nagle. Mogul and Minshall note a client that
buffered input for a few imperceptible milliseconds would turn this back into case 2.

---

## 6. Fixes

**Five sender-side modifications**, including a novel one that *"directly attacks the deadlock, by
treating it as a form of priority inversion"*, plus a **receiver-side** change that helps in some
circumstances. The deadlock-detection approach **fully eliminates the problem in their benchmark**,
though the authors say **it is not appropriate to every application**. Implemented and measured in
a **BSD-derived TCP**.

---

## 7. What this means for our work

**The pack cites this correctly** — for *"the well-known potential for deadlock between the Nagle
algorithm and the delayed ACK policy"*. Three things in it we are not using.

**1. The prevalence number.** **6.7% to 18.8% of HTTP responses in a real trace have a
OF+SFS-vulnerable length**, and at the Ethernet MSS it is **10-19%**. Our `nagle_delayed_ack`
family currently has mechanism sources (RFC 896, RFC 1122, Cheshire, Brooker) but no measured
"how often does this shape occur". **This is it**, and it is from a real HTTP trace, which is
exactly our workload shape.

**2. The trigger condition is precise enough to design an injection against.** A message strictly
between **(2N+1)·MSS and (2N+2)·MSS**, nothing below 2·MSS. With MSS 1460 that is **2,921-4,379
bytes**, then 7,301-8,759, and so on. If our fault recipe does not target a payload in one of
those bands, **it may not reproduce the deadlock at all** — and the fault would look like a null
result when it is really a mis-specified injection. **Worth checking the recipe against these
bands before running the family.**

**3. Sock Shop is class 4, the unfixable one.** Their taxonomy puts **NFS over TCP and persistent
HTTP in class 4** — pipelined exchanges where the client does not wait for a full response.
**Modern microservice traffic is exactly this**: HTTP keep-alive, gRPC streams, connection
pooling. So:

- The family is **well-motivated** — it is the case Nagle genuinely cannot serve.
- And the expected real-world fix is **`TCP_NODELAY`**, which is why most microservice runtimes
  set it by default. **That is a rule-out our blueprint needs**: if the service already sets
  `TCP_NODELAY`, the fault cannot occur, and our injection must be disabling it.

**A discriminator that falls out of the mechanism.** The deadlock ends when **the delayed-ACK
timer fires**, which is **200 ms on BSD-derived stacks and up to 500 ms by specification**. Linux
uses a variable delayed-ACK timeout, but the shape is the same: **a quantised delay, not a
distributed one**. That is unusually easy to see in a kernel trace:

| | `nagle_delayed_ack` | `network-path-degradation` |
|---|---|---|
| Delay distribution | **clustered at a fixed timer value** | **continuous / variable** |
| Depends on payload size | **yes — only in the OF+SFS bands** | no |
| Packets in flight | **sender has data queued and is not sending** | data is sent, arrives late |

**A quantised delay at a timer boundary is a signature**, in the same way that throttling's 100 ms
CFS period is. Both are cases where the kernel's own timer leaves a fingerprint. **Hypothesis to
test, not a finding.**

**One honest scope note.** This is **2001, BSD-derived stacks**. Linux has carried **Minshall's
variant** and TCP small-queues for many years, and Linux's delayed-ACK timer is adaptive rather
than a flat 200 ms. **We must not claim our VM's kernel 7.0.0 behaves like the BSD stack they
measured.** Cite the mechanism and the OF+SFS condition; measure the timing ourselves.

**And the framing is good for the introduction.** Nagle is *"a mechanism to protect the Internet
against excess packets sent by buggy applications"*, disabled by people avoiding a symptom they do
not understand — with the result that the protection is absent when it is needed. **That is a
performance fault whose usual "fix" creates a different risk**, which is a more interesting story
than a plain latency bug, and one our blueprint can tell.

---

## 8. Safe claims

- **Nagle:** send data smaller than the MSS **only if all previously transmitted data has been
  acknowledged**.
- **Delayed ACK** (1982): delay the ACK to piggyback it on reverse-path data; ACK at least every
  **second full-sized segment (2 × MSS)**; a timer, **typically 200 ms and allowed up to 500 ms**,
  bounds the delay. **BSD-based systems limit it to 200 ms.**
- The two combine into a **temporary deadlock**: the sender waits for an ACK, the receiver waits
  for data. It breaks only when the delayed-ACK timer fires, **adding up to 200-500 ms to
  operations that should be far faster**, and is **especially visible on LANs and regional
  networks**.
- **Nagle analysed his algorithm for deadlock and missed this one**; delayed ACKs were not yet
  widely implemented.
- The deadlock arises for messages needing an **odd number of full segments plus a short final
  segment (OF+SFS)** — length strictly between **(2N+1) × MSS and (2N+2) × MSS**. Messages
  **shorter than 2 × MSS are never delayed**, nor are messages shorter than **MCLBYTES**.
- In a real HTTP trace, **6.71% to 18.78% of responses had OF+SFS-vulnerable lengths**; at
  **MSS = 1460 it is 10.05-18.78%**.
- Four application classes: **bulk transfer** and **Telnet-style** work fine with Nagle;
  **RPC-style** is problematic but **fixable** by minor modification; **pipelined soft-realtime
  exchanges (NFS over TCP, P-HTTP) cannot be fixed**, because wanting a small message sent
  immediately is *"antithetical to the original intent of the Nagle algorithm"*.
- Disabling Nagle **"can lead to severe network stress when done by an application with faulty
  output buffer management"**, and many implementors disable it *"in circumstances where this
  should not be required"*.
- The algorithm behaves poorly **when the application buffer is smaller than the MSS**;
  implementors should use appropriate buffering.
- They propose **five sender-side modifications** plus a **receiver-side** change; the
  deadlock-detection approach **fully eliminates the problem in their benchmark** but **is not
  appropriate to every application**. Implemented in a **BSD-derived TCP**.

## 9. Do NOT claim

- That the 200 ms figure describes Linux. The paper measures **BSD-derived stacks in 2001**; Linux
  uses an **adaptive** delayed-ACK timeout and has long carried **Minshall's variant**.
- That 6.7-18.8% is a rate of *observed* delays. It is the fraction of responses whose **length**
  makes them vulnerable, from a model applied to a trace.
- That disabling Nagle is the right fix generally. The paper's central argument is the opposite
  for classes 1-3.
- That the fix works everywhere. The authors say their deadlock-detection modification **is not
  appropriate to every application**, and class 4 is unfixable in principle.

## 10. Reusable ideas

- **Name the exact trigger condition.** "(2N+1)·MSS to (2N+2)·MSS" is what turns a known
  folk-problem into something you can inject, detect, and count.
- **Measure how often the condition occurs in real traffic.** The HTTP-trace table converts a
  mechanism into a prevalence claim.
- **Classify who should and should not apply the workaround.** Four application classes, with one
  declared unfixable. Our blueprints' `applies_to` fields want the same discipline.
- **A timer-bounded delay is quantised, and quantised delays are visible.** Same lesson as the
  100 ms CFS period in blueprint 10.
- **The reflexive workaround has its own cost.** Disabling Nagle removes a protection the network
  relies on. Worth stating in any remediation advice a blueprint gives.
