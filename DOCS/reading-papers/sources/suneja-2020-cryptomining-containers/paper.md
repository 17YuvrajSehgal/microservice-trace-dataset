# Paper Context: Cryptomining Detection in Container Clouds Using System Calls and Explainable Machine Learning (IEEE TPDS 2021)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> The nearest published work to our **`resource_abuse`** fault: cryptomining, **in containers**,
> detected from **system calls**. **Our citation of it is wrong in three ways** — first author,
> venue, and year. See §1 and §9.

---

## 1. Bibliographic info — corrected

**Our `meta.yaml` and `FUTURE-BLUEPRINT-REFERENCES.md` both say "Suneja et al., IPDS 2020". That
is wrong on three counts.** The paper is:

- **Title:** Cryptomining Detection in Container Clouds Using System Calls and Explainable
  Machine Learning
- **Authors:** **Rupesh Raj Karn**, Prabhakar Kudva, Hai Huang, **Sahil Suneja**,
  Ibrahim (Abe) M. Elfadel — Suneja is the **fourth** author, not the first
- **Venue:** **IEEE Transactions on Parallel and Distributed Systems, vol. 32, no. 3, March 2021,
  pp. 674-691** — a journal, not "IPDS"
- **DOI:** 10.1109/TPDS.2020.3029088
- Manuscript received 27 Jan 2020, revised 25 July 2020, accepted 30 Sept 2020. **The 2020 date
  is the acceptance year; the publication is 2021.**
- Appendix with the collection scripts is in the IEEE Computer Society Digital Library.

```bibtex
@article{karn2021cryptomining,
  title   = {Cryptomining Detection in Container Clouds Using System Calls and Explainable Machine Learning},
  author  = {Karn, Rupesh Raj and Kudva, Prabhakar and Huang, Hai and Suneja, Sahil and Elfadel, Ibrahim M.},
  journal = {IEEE Transactions on Parallel and Distributed Systems},
  volume  = {32}, number = {3}, pages = {674--691}, year = {2021},
  doi     = {10.1109/TPDS.2020.3029088}
}
```

**Cite it as Karn et al. 2021.** The slug `suneja-2020-cryptomining-containers` can stay as a
directory name, but the reference must be fixed.

---

## 2. One-paragraph summary

An attacker can swap a healthy container image for an infected one, and Docker Hub has hosted
many such images — accessible without authentication, so cryptojacking spreads through them. The
miner then **shares the pod's CPU and memory with the legitimate application**, and in the worst
case leaves it only a fraction. The authors detect this in a **Kubernetes cluster** by collecting
**Linux system calls per pod with `perf`**, turning them into **n-gram features**, and training
four ML models. **A decision tree reaches 97.1% validation accuracy**; the deep models do far
worse. They add **explainability (LIME, SHAP, an autoencoder scheme)** because an administrator
about to delete a pod needs a reason. Runtime overhead of the monitoring is **about 5%**.

---

## 3. Why not just look at CPU

This is the argument that matters most for us, and they state it directly:

> Cryptominers are known to be CPU intensive... One method for detecting cryptominers may be
> based on CPU usage or usage rate. **Although it is a good first-order metric, some healthy
> application might be CPU-intensive and show significant changes in CPU usage, creating false
> alerts** or in the worst case, triggering the disabling of an important healthy workload.
> **Syscalls provide a second-order metric.**

So the whole paper exists because **CPU share alone cannot separate a miner from a legitimately
busy workload**. To make that a fair test they deliberately built a benign population that is
**also CPU-heavy**.

---

## 4. The workloads

**8 miners**, chosen to span the Proof-of-Work algorithm space: SHA256, cryptonight, X11,
Lyra2RE, Equihash. Named pods include Bitcoin, Bytecoin, Vertcoin, Dashcoin, Litecoin.

**8 benign, CPU-intensive applications** — deliberately 8 to match, *"to avoid inference problems
related to data imbalances"*: picture classification with deep learning, MySQL performance
testing, Cassandra stress, Apache Spark from CloudSuite, single-node Hadoop map-reduce, Docker
Bench for Security, a graph analytics benchmark, a media streaming benchmark.

---

## 5. Collection — practical details worth having

- **`perf`** is run **on the host server**, collecting raw syscalls per time window. They note
  `strace` and `ptrace` work similarly, and that **Sysdig — the usual choice — is not fully
  open source**, its premium version needing a licence. `perf`, `strace` and `ptrace` ship with
  Linux.
- **Syscall collection in Docker is simple; in Kubernetes it takes extra steps**, which is why
  they publish the scripts. They say little information was available for the Kubernetes case.
- **Round-robin polling.** With N containers and sampling interval Δt, each pod is polled every
  **T = N·Δt**, which **grows linearly with N**. They argue **Δt = 1 minute** suffices because
  *"mining is a long-term activity that is usually run for days (as opposed to short-term
  malware)"*.
- **Storage is the real cost.** At Δt = 1 minute:

| Pod | Raw syscall file (MB) | Sequence length | Mean interval between syscalls (s) |
|---|---|---|---|
| **Bitcoin** | **554** | 2,038,829 | 0.000029 |
| Hadoop | 480 | 1,656,599 | 0.0000362 |
| Cassandra | 246 | 910,472 | 0.0000658 |
| Bytecoin | 134 | 481,466 | 0.00012 |
| Litecoin | 83 | 290,657 | 0.000206 |
| Deeplearning | 22 | 77,981 | 0.000769 |
| Dashcoin | 18 | 61,634 | 0.00097 |
| Vertcoin | 8 | 28,850 | 0.00207 |
| MySQL | 5 | 14,756 | 0.00406 |

**The dynamic range is enormous — 5 MB to 554 MB per minute**, and note that **Hadoop and
Cassandra (benign) produce more than most miners.** Volume is not the signal.

- **Runtime overhead is about 5%**, measured by running workloads twice, with and without
  collection. They call it reasonable.
- **Security note they raise honestly:** an attacker who tunnels to the host **can kill the
  `perf` process**, after which no syscalls are collected at all.

---

## 6. Method and results

Pipeline: raw syscalls → **n-gram** frames (chosen over PCA, which they call too computationally
intensive for real time) → 70:30 train/validation split → four models.

| Model | Validation accuracy | Training | Precision | Recall | F1 | Cohen's κ | ROC AUC |
|---|---|---|---|---|---|---|---|
| **Decision tree** | **97.1%** | 99.6% | 0.97 | 0.97 | 0.97 | 0.9403 | 0.9701 |
| XGBoost ensemble | 89.4% | 89.3% | 0.90 | 0.89 | 0.90 | 0.7808 | 0.8838 |
| Feed-forward ANN | 79.7% | 81.1% | 0.7461 | 0.9703 | 0.8405 | 0.5674 | 0.8885 |
| RNN with LSTM | 78.9% | 79.99% | 0.7374 | 0.9731 | 0.8358 | 0.5491 | 0.8669 |

Cost:

| Model | Training time | Prediction time | Resource use |
|---|---|---|---|
| Decision tree | **2.7 s** | **0.02 s** | CPU 97%, 243 MB |
| XGBoost | 18.7 s | 0.25 s | CPU 165%, 367 MB |
| Feed-forward ANN | 35.1 s | 2.0 s | CPU 335%, 182 MB |
| RNN + LSTM | **1340 s** | **7.6 s** | CPU 385%, 242 MB |

**The simplest model wins on every axis** — accuracy, speed, and resource use. The LSTM is 500×
slower to train and 18 points less accurate.

Explainability: **LIME** for the decision tree and vanilla ANN, **SHAP** for XGBoost, and a
**novel autoencoder-based scheme** for the LSTM.

### The set-theoretic analysis — the most reusable part

They take the union of syscalls used by all 8 miners (W_miner) and all 8 benign apps (W_normal),
then:

| Set | Definition | Size |
|---|---|---|
| W_miner | all syscalls any miner made | **100** |
| W_normal | all syscalls any benign app made | **116** |
| **Sig_miner** = W_miner − W_normal | **only miners make these** | **12** |
| **Sig_normal** = W_normal − W_miner | only benign apps make these | **28** |
| **Sig_confuse** = W_miner ∩ W_normal | made by both | **88** |
| Sim_miner | made by **all 8** miners | **7** |
| Sim_normal | made by **all 8** benign apps | **1** |

The actual sets, **given as syscall numbers, not names**:

- **Sig_miner = {288, 98, 35, 293, 263, 264, 47, 23, 25, 187, 285, 286}**
- Sig_normal = {131, 267, 140, 160, 162, 40, 43, 53, 57, 186, 62, 63, 192, 268, 204, 84, 213, 88,
  90, 58, 95, 100, 229, 234, 109, 111, 112, 115}
- **Sim_miner = {1, 3, 228, 41, 42, 55, 202}**
- Sim_normal = {1}

Their reading: **|Sim_normal| = 1** means the benign benchmarks are *"very different"* from each
other, while **|Sim_miner| = 7** means the miners share behaviour despite different PoW
algorithms — and that shared core is what makes classification work.

**These are raw x86-64 syscall numbers.** Map them against the kernel's syscall table before
using any of them; the paper does not give names.

---

## 7. What kind of paper this is

- A **detection system with an ML classifier**, evaluated on a Kubernetes cluster the authors
  built.
- Signal is **syscall sequences sampled by `perf`**, aggregated into n-grams. **No timing, no
  scheduler events, no per-event ordering beyond the n-gram.**
- The output is **a binary label per pod**, plus an explanation of which n-grams drove it.
- It is a **security** paper: the adversary is deliberate.

---

## 8. What this means for our work

**It is the right citation for `resource_abuse`, and it makes the case for the fault better than
we do.** Cryptojacking through poisoned Docker Hub images is a documented, real attack, and the
victim is exactly our setup: a co-located container quietly eating the host's CPU.

**Their core argument is our coverage sweep's problem, stated by someone else.** Our sweep found
`resource_abuse` *"runs a hidden CPU loop, so it is probably not separable from `noisy_neighbor`
at all"*. Karn et al. say the same thing about the same signal — **CPU share is a good
first-order metric but produces false alerts on legitimately busy workloads** — and their answer
is to move to a different axis: **which syscalls, not how much CPU**.

**And we have that axis, in a stronger form.** They sample syscalls **once a minute per pod,
round-robin**, so their view of any pod is a snapshot. We record **every syscall, continuously,
with timestamps and `pid_ns`**. If a 12-syscall signature separates miners from CPU-heavy benign
work at 97% from sampled n-grams, the same distinction should be at least as available to us.
**That is a hypothesis for the `resource_abuse` blueprint, and the first thing to test is whether
our `resource_abuse` recipe produces any syscall-set difference at all** — our fault is a
synthetic CPU loop, and a synthetic loop may make *no* distinctive syscalls, in which case the
sweep's verdict stands and this paper does not rescue it.

**The honest version of that:** their miners are real mining binaries doing real work — network
I/O to a pool, file writes, timers. Our injected `resource_abuse` may be a bare spin loop. **If
so, this paper's method does not apply to our fault, and we should say that rather than cite it
as support.** Check the recipe before citing.

**Two of their numbers bear directly on our collection design.**

- **Volume is not the signal.** Hadoop and Cassandra produced *more* syscalls per minute than 4
  of the 5 named miners. Any rate-based discriminator we write for `resource_abuse` is suspect.
- **~5% runtime overhead from `perf` sampling.** A useful comparison point for our LTTng
  numbers, though theirs is a 1-minute sample per pod and ours is continuous — not comparable
  without saying so.

**One methodological result we should copy outright.** **The decision tree beat the LSTM by 18
points while training 500× faster.** With Kohyarnejadfard's LSTM already in our reference set,
this is a useful counterweight: on syscall data, the simple model won, and the authors published
that rather than burying it. Our blueprints are rule-based; this is evidence that rules are not
a compromise.

**The set-theoretic framing is worth stealing for every fault family.** "Which syscalls appear
under fault X and never under normal operation" is computable from our data for all 24 families
at once, and it would give each blueprint a `Sig_fault` set derived from measurement rather than
reasoning. **Their |Sig_confuse| = 88 out of 100 is the sobering half**: most syscalls are shared,
and the discriminative set is small.

---

## 9. Citation corrections needed in our own files

| File | Currently says | Should say |
|---|---|---|
| `sources/suneja-2020-cryptomining-containers/meta.yaml` | `authors: Suneja, S. et al.` / `venue: IEEE IPDS 2020` / `year: 2020` | `Karn, R. R. et al.` / `IEEE TPDS 32(3):674-691` / `2021` |
| `FUTURE-BLUEPRINT-REFERENCES.md` | "Suneja et al., IPDS 2020" | "Karn et al., IEEE TPDS 2021" |

Neither is in a blueprint or a skill, so no run is affected.

---

## 10. Safe claims

- Attackers replace healthy container images with infected ones; **Docker Hub has hosted images
  used for cryptomining**, accessible without authentication.
- A miner **shares the pod's CPU and memory with the legitimate application**, and can leave it
  only a fraction.
- **CPU usage is a good first-order metric but produces false alerts**, because legitimate
  workloads can also be CPU-intensive. **Syscalls are a second-order metric.**
- Setup: **8 miners** spanning SHA256, cryptonight, X11, Lyra2RE and Equihash, against **8
  CPU-intensive benign workloads** (deep learning, MySQL, Cassandra stress, Spark/CloudSuite,
  Hadoop, Docker Bench, graph analytics, media streaming), balanced 8:8 on purpose.
- Collection with **`perf` on the host**, **round-robin** across pods, sampling interval **Δt = 1
  minute**; per-pod polling period **N·Δt grows linearly with the number of containers**.
- **Runtime overhead about 5%.**
- Storage per minute ranges from **5 MB (MySQL) to 554 MB (Bitcoin)**; **Hadoop (480 MB) and
  Cassandra (246 MB), both benign, exceed most miners.**
- Features are **n-grams** of the syscall sequence, chosen over PCA as cheaper for real time;
  70:30 train/validation split.
- **Decision tree: 97.1% validation accuracy, F1 0.97, κ 0.9403, 2.7 s training, 0.02 s
  prediction.** XGBoost 89.4%, feed-forward ANN 79.7%, **LSTM RNN 78.9% after 1,340 s of
  training.**
- Explainability via **LIME** (tree, ANN), **SHAP** (XGBoost), and a **novel autoencoder scheme**
  (LSTM), because administrators need a justification before deleting or restarting a pod.
- Set analysis: **100 distinct syscalls across all miners, 116 across all benign apps; 12 unique
  to miners, 28 unique to benign, 88 shared**; **7 syscalls common to all 8 miners** versus
  **1 common to all 8 benign apps**.
- An attacker who reaches the host **can kill the `perf` process**, stopping all collection.

## 11. Do NOT claim

- **"Suneja et al., IPDS 2020."** It is **Karn et al., IEEE TPDS 32(3), 2021**. Suneja is the
  fourth author.
- That the syscall numbers in `Sig_miner` are a ready-made signature. They are **raw x86-64
  numbers with no names given**, derived from 8 specific miners against 8 specific benign
  workloads.
- That 97.1% is a deployment result. It is **validation accuracy on their own balanced 8-vs-8
  dataset**, not a false-positive rate in a real cluster.
- That the method sees timing or ordering beyond the n-gram window. It samples **one minute per
  pod, round-robin**.
- That it is comparable to our continuous LTTng collection, or that its 5% overhead is comparable
  to ours.

## 12. Reusable ideas

- **Move to a second-order metric when the first-order one has false positives.** CPU share
  cannot separate a miner from a busy database; the set of syscalls can. This is the general form
  of what our blueprints do.
- **Make the control population hard on purpose.** Choosing 8 *CPU-intensive* benign workloads is
  what makes the result mean anything. A miner beats an idle pod trivially.
- **Set-theoretic signatures.** `Sig_fault = W_fault − W_normal` is computable for every fault we
  have, and it turns a discriminator from an argument into a measurement. Expect it to be small —
  theirs was 12 out of 100, with 88 shared.
- **Publish the model comparison including cost.** A decision tree beating an LSTM by 18 points
  at 1/500 the training time is a result, and it is the kind that usually goes unreported.
- **Say how the monitoring itself can be defeated.** Killing `perf` kills the detector. Any
  security-adjacent blueprint of ours should state its equivalent.
