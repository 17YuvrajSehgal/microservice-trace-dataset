# Paper Context: Taking the Blame Game out of Data Centers Operations with NetPoirot (SIGCOMM 2016)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> Cited by blueprint 2 as *"the closest academic match to diagnose the network from the host"*,
> and that is accurate. Its framing — **blame allocation between client, network and server** —
> is the clearest statement in the pack of the problem our WHERE axis solves. See §8.

---

## 1. Bibliographic info

- **Title:** Taking the Blame Game out of Data Centers Operations with NetPoirot
- **Authors:** Behnaz Arzani, Selim Ciraci, Boon Thau Loo, Assaf Schuster, Geoff Outhred
  (Microsoft and University of Pennsylvania)
- **Venue:** ACM SIGCOMM 2016
- **DOI:** 10.1145/2934872.2934884
- Named after Agatha Christie's detective Hercule Poirot.

```bibtex
@inproceedings{arzani2016netpoirot,
  title     = {Taking the Blame Game out of Data Centers Operations with {NetPoirot}},
  author    = {Arzani, Behnaz and Ciraci, Selim and Loo, Boon Thau and Schuster, Assaf and Outhred, Geoff},
  booktitle = {SIGCOMM 2016}, year = {2016},
  doi       = {10.1145/2934872.2934884}
}
```

---

## 2. One-paragraph summary

When a distributed service misbehaves, the hardest question is **whose fault it is** — the
client, the network, or the remote service. Each team sees only its own logs, so the issue gets
passed around while the outage continues. NetPoirot answers that question from **one place
only**: a lightweight TCP monitoring agent on the **client** machine. The insight is that
**failures that are not network failures still make TCP behave differently**, and those
differences are learnable. A decision tree over periodically sampled TCP metrics does
coarse-grained blame allocation, reaching **96% accuracy for some failure types**, with **no
knowledge of the application** and nothing deployed on the network or the server.

---

## 3. The motivating story — worth reading in full

Their production cloud serves **over 1 billion customers**. A VM triggers an operation in the
hypervisor, which sends a request to a remote service. When request/response latency rises —
from remote service failure, overload, or network slowdown — the hypervisor errors and **the VM
panics and reboots**. They call it **"Event X"**.

What happened when it occurred:

1. The **remote service DevOps team** was contacted first. They suspected high
   request/response latency, **blamed the network**, and passed it on.
2. The **network engineers** saw normal RTT in TCP traces and suspected **slow server
   responses**, and handed it back.
3. *"The iterations continued until the various teams involved pieced together the sequence of
   events."*

They add two things that make it worse: **the same symptom can have different causes on
different occurrences**, and **fixing one occurrence may not prevent others**.

### Why this is structurally hard

- The parties diagnosing it — service DevOps, network operators — **are different organisations**,
  within or across companies, and **each lacks access to the other's logs**.
- The failures are **intermittent and non-deterministic**, so they cannot be reproduced without
  always-on, high-fidelity monitoring everywhere.

### Why existing tools did not help

Some require **access to the entire system**; some are **too heavyweight to run always-on**;
some need **information the service or network will not share**. They note pointedly that their
own organisation had already adopted several of these tools, and they still could not diagnose
Event X.

---

## 4. The key insight

> **Different types of failures, albeit not network related, will cause TCP to react
> differently.**

Their own examples, which are the most useful part of the paper for us:

| Failure | How TCP reacts on the client |
|---|---|
| **Slow-reading remote service** | exhausts the TCP receive window on the sender, which triggers **zero-window probing** |
| **Packet drops on a router** | an increase in **duplicate ACKs** |
| **High CPU load on the client** | fewer transmission opportunities, so **less data sent by TCP** |

They are candid that these are *"not always easy to define, given the high correlation between
the various TCP metrics"* — which is why they learn the boundaries rather than writing rules.

---

## 5. Design

- **A TCP monitoring agent on every client VM.** Nothing on the network, nothing on the server.
- Captures TCP metrics **periodically**. Implemented in Windows; they note a Linux equivalent
  is possible.
- **Decision trees**, chosen partly because they **identify which TCP metrics dominate the
  classification** for each failure type.
- **Requires no knowledge of the application.**
- SNMP and network topology can improve accuracy *if available* — but they note such data is
  often unavailable or expensive to collect at high fidelity, so the goal is explicitly *"the
  extent to which failure diagnostics can be achieved simply by using data available through
  the clients."*

---

## 6. Results

- **Coarse-grained blame allocation with high accuracy — 96% for some failure types.**
- Accuracy improves further with additional information.
- Evaluated on real failures in their data centres, across a variety of failure types.
- A methodological detail worth noting: partitioning the data **by machine label** gave
  **10.55% error**, which they take as evidence that data from the same machine behaves
  differently — i.e. per-machine effects are real and must be controlled for.

---

## 7. What kind of paper this is

- A **deployed monitoring system** with a machine-learning classifier, evaluated in a
  production cloud.
- The output is **which entity to blame** (client / network / server), not a root cause.
- It is explicitly **coarse-grained** — the authors say so.
- Signal is **TCP stack metrics**, not kernel traces.

---

## 8. What this means for our work

**The framing is the most valuable thing here, and blueprint 2 already uses it correctly.**
"TCP-level signals at the end host alone can tell whether a fault is in the client, the network
or the server" is exactly what the paper shows.

**The blame-allocation problem is our WHERE axis, stated by someone else.** Their whole paper
exists because *"the team that owns the failure can then provide a timely response, rather than
have the error be passed around."* That is a better motivation for localisation than anything
we have written, and it comes with a concrete production story.

**Their three TCP reactions are a checklist we should test against our own data:**

| Their signal | Our nearest equivalent |
|---|---|
| zero-window probing → slow reader | we do not decode TCP flags; `ctf_lines` could show it in a raw packet line |
| duplicate ACKs → packet loss | we infer loss from **timing gaps**, since `tcp_retransmit_skb` is not enabled |
| less data sent → client CPU load | `net_dev_xmit` byte volume, which we do have |

The reference pack already states the limit correctly: *"say that you infer loss from timing
gaps, because LTTng does not directly record TCP retransmits unless you enable the
`tcp_retransmit_skb` tracepoint."* NetPoirot gets duplicate ACKs because it reads the TCP stack
directly. **We do not have that signal**, and this paper is the evidence that it is the one
worth having.

**Where we differ, and it is in our favour on one axis.** NetPoirot classifies to
client/network/server — three buckets. We name a **specific container**. Their output is
coarser by design, because they cannot see inside the remote service at all. Our position is
the opposite: one host, full visibility, no cross-organisation boundary.

**And where it is in their favour.** They run **always-on in production across a
billion-customer cloud**. We run offline on recorded traces. Any claim we make about
practicality should not be compared to theirs.

**One methodological warning we should heed.** Their 10.55% error when partitioning by machine
means **per-machine variation is large enough to matter**. Our own v1 study had Sock Shop and
Train Ticket in different regions, which we flagged as a confound and fixed in v2 by putting
both in `us-east1-d`. This paper is independent evidence that the concern was real.

---

## 9. Safe claims

- Diagnosing whether a failure belongs to the client, the network or the remote service is hard
  because **the parties are different organisations and cannot see each other's logs**.
- Such failures are often **intermittent and non-deterministic**, so they cannot be reproduced
  without always-on monitoring everywhere.
- **Failures that are not network failures still change how TCP behaves**, and those differences
  are learnable: a slow reader exhausts the receive window and triggers zero-window probing;
  router packet drops raise duplicate ACKs; high client CPU means less data sent.
- NetPoirot does coarse-grained blame allocation from a **client-side TCP agent only**, with no
  application knowledge and nothing deployed on the network or server.
- **Accuracy up to 96% for some failure types**, improving with extra information.
- Decision trees were chosen partly because they reveal which TCP metrics dominate each
  classification.
- Partitioning data by machine gave **10.55% error**, indicating real per-machine variation.
- Existing tools failed on their production case because they need whole-system access, are too
  heavyweight for always-on use, or need data the parties will not share.

## 10. Do NOT claim

- That NetPoirot identifies a root cause. It allocates **blame** to one of three entities and
  the authors call it coarse-grained.
- That it uses kernel traces. It reads **TCP stack metrics** via a client agent.
- That 96% is an overall accuracy. It is "for some failure types".
- That we can reproduce its signals. We do not decode duplicate ACKs or zero-window probes.

## 11. Reusable ideas

- **Ask "whose fault is it" before "what is the root cause".** Blame allocation is a smaller,
  more answerable question, and it is the one that unblocks a response.
- **A non-network failure still perturbs the network stack.** Second-order effects on a shared
  layer can identify a first-order cause elsewhere.
- **Choose a model that tells you which feature mattered.** Their reason for decision trees is
  the same reason our blueprints must name the deciding signal.
- **Control for the machine.** 10.55% error from a per-machine split is a reminder that
  "collected on different hardware" can masquerade as a finding.
- **Measure what one vantage point can do before asking for more.** Their explicit goal was to
  find the limit of client-only data. Ours is the limit of kernel-only data.
