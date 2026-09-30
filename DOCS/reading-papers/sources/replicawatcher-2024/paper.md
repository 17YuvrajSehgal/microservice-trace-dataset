# Paper Context: REPLICAWATCHER — Training-less Anomaly Detection in Containerized Microservices (NDSS 2024)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> Our pack calls it *"the closest match to your setting"* — containerised microservices, kernel
> events, an exfiltration scenario. That is right. **It also contains a measurement that should
> change how we read our own rate-based discriminators**: identical replicas doing identical work
> have *substantially dissimilar* syscall frequencies. See §8.

---

## 1. Bibliographic info

- **Title:** REPLICAWATCHER: Training-less Anomaly Detection in Containerized Microservices
- **Authors:** Asbat El Khairi (University of Twente), Marco Caselli (Siemens AG),
  Andreas Peter (University of Oldenburg), Andrea Continella (University of Twente)
- **Venue:** **NDSS 2024**
- **Tool:** https://github.com/utwente-scs/Replicawatcher

```bibtex
@inproceedings{elkhairi2024replicawatcher,
  title     = {{REPLICAWATCHER}: Training-less Anomaly Detection in Containerized Microservices},
  author    = {El Khairi, Asbat and Caselli, Marco and Peter, Andreas and Continella, Andrea},
  booktitle = {NDSS 2024}, year = {2024}
}
```

**Our pack lists this as "[S; check authors]".** Authors confirmed above.

---

## 2. One-paragraph summary

Anomaly detection needs a baseline of "normal", and in microservices **normal keeps moving** —
image updates, dependency bumps, new features. Every drift produces previously unseen syscalls and
therefore false positives, so training-based detectors need constant retraining. REPLICAWATCHER
removes the baseline entirely: **compare each container against its own replicas.** Replicas exist
anyway for scaling and fault tolerance, they run identical images and identical work, so **a
compromised replica stands out from its siblings** without any prior training. Evaluated on **13
attack scenarios** across two microservice applications: **average precision 91.08%, recall
98.35%**, and — the actual claim — **performance holds across version updates where the
training-based baselines collapse.**

---

## 3. The motivating measurement — normality drift is real and small

They monitored the **`cart` microservice of Google Online Boutique across its last ten versions
over nine months**, running each version for three hours and recording syscalls executed by a new
version but not its predecessor.

**Almost every new version introduces one previously unseen syscall.**

Their worked example: upgrading `cart:0.6.0` → `cart:0.7.0` bumped the .NET SDK from 7.0.201 to
7.0.302 and `GRPC_HEALTH_PROBE` from 0.4.15 to 0.4.18. The new syscall that appeared was
**`getrlimit`** — a process asking for its own resource limits. Entirely benign, and enough to
trigger false positives in a syscall-baseline detector.

Context they give: **Netflix makes hundreds of production changes per day.**

---

## 4. The feature study — the part most useful to us

Before building anything they asked which observable features are **stable across replicas** under
normal operation. They grouped candidates into three kernel-level families — **syscalls, file
descriptors, and processes** — and ranked every feature by its **maximum dissimilarity across
replicas**.

> Features such as **syscall frequency, network IP addresses and ports, latency, delta time, and
> buffer length exhibit substantial dissimilarity across replicas.** This can be attributed to
> factors such as **varying workloads, network conditions, and user behavior**. Conversely, **all
> process-based features manifest little to no dissimilarity**.

So:

| Feature family | Dissimilarity across identical replicas | Usable? |
|---|---|---|
| **Syscall frequency** | **substantial** | **rejected** |
| Network IPs and ports | substantial | rejected |
| **Latency, delta time** | **substantial** | **rejected** |
| Buffer length | substantial | rejected |
| **Process-based features** | **little to none** | **selected** |

Selection rule: **maximum dissimilarity below 0.2**, at a **30-second monitoring interval**.

They also measured that **longer intervals give greater similarity** — the broader window,
synchronisation of environmental conditions over time, and stabilising resource use and user
behaviour all help. 30 s was their compromise.

---

## 5. Design and deployment

- **Sysdig** with a **custom Chisel** captures kernel events, deployed as a **privileged
  DaemonSet** on worker nodes. They acknowledge this gives attackers something to tamper with.
- Events → features → **similarity comparison across the replica set** → anomaly score.
- **No training phase, no baseline database, no retraining.**
- Runs as an HIDS **on the worker nodes** rather than a central server, to avoid communication lag.

---

## 6. Evaluation

**Two applications:**

1. A **"homebrew" e-commerce application with seven microservices** (checkout, cart, and others),
   each deliberately built on a different technology, with **vulnerabilities from common software
   libraries embedded on purpose**.
2. **Google Online Boutique (GOB)**, 11 microservices, with **three injected vulnerabilities**.

**13 attack scenarios**, real CVEs, mapped to specific microservices:

| Threat impact | CVEs | Target service |
|---|---|---|
| Information Disclosure | CVE-2019-5418, CVE-2018-3760, CVE-2017-14849 | checkout, payment |
| **Remote Code Execution** | CVE-2017-12636, CVE-2022-24706, CVE-2012-1823, CVE-2018-19518, **CVE-2014-6271 (ShellShock)** | product DB, login, signup, **cart** |
| Privilege Escalation | CVE-2017-12635 | product DB |

Plus PHP-LFI and CWE-434 scenarios.

**Setup:** two-node GKE cluster, `e2-standard-4` (4 vCPU, 16 GB), Ubuntu + containerd. Replicas
varied from **two to six** per microservice. Normal mode: **30-50 users** with benign patterns.
Attack mode: the same plus one attacker.

**Dataset:** per vulnerable microservice, **1,000 normal and 250 attack snapshots**, split evenly
across five replica-count settings. A snapshot is **30 seconds** of replica behaviour. **Total:
15,000 normal and 3,750 attack snapshots — six days of monitoring.**

### Results

- **GOB scenarios: average AUC 0.9960.** Homebrew scenarios: **average AUC 0.9827.**
- At a **uniform threshold ε = 0.3**: **average precision 0.9248, recall 0.9813.** (The abstract
  quotes 91.08% / 98.35%.)
- Per-scenario AUC ranges from **0.9479** (CVE-2012-1823 command injection) to **0.9999**
  (CVE-2022-24706).
- **Weakest cases:** precision drops on PHP-LFI, CWE-434 and ShellShock, where *"the uniform
  threshold struggles to differentiate between attacks and the inherent noise from regular
  microservice usage."* Recall drops on **CVE-2018-3760 path traversal**, because those attacks
  *"introduce only subtle variance among replicas."*
- **Known limitation: authentication bypass attacks.**

### The comparison that is the actual contribution

Against three training-based container HIDSes — **STIDE-BoSC**, **CHIDS**, and **CDL** — measured
**before and after** three kinds of update: base OS image, dependency package, and application
code. **REPLICAWATCHER holds its true-positive and false-positive rates across the update; the
baselines degrade substantially.**

### Cost

Full pipeline — chisel execution, log generation, snapshot grouping, encoding, classification —
scales **sublinearly** with replica count. At **48 pods (8 microservices × 6 replicas)**, which
they note *"aligns with the median container-per-host density observed in real-world settings"*,
it **processes and classifies in under 2.25 seconds**.

---

## 7. What kind of paper this is

- A **security detection system**, evaluated on real CVEs in containerised microservices.
- Signal is **kernel events via Sysdig**, aggregated into 30-second snapshots.
- The output is **which replica is anomalous** — a container-level label, not a root cause.
- **Requires replicas.** A singleton service has nothing to compare against.

---

## 8. What this means for our work

**Our pack's description is correct: this is the closest published work to our setting.** Kernel
events, containers, microservices, per-container attribution, and a real Kubernetes deployment.
When we say kernel-level signals can localise to a container, this is the nearest precedent.

**But the most valuable thing in it is a number that should make us re-read our own blueprints.**

> **syscall frequency ... latency, delta time ... exhibit substantial dissimilarity across
> replicas** ... **all process-based features manifest little to no dissimilarity**

They measured this on **identical container images running identical code under the same load
balancer**, and syscall *rate* was too noisy to use. **Many of our discriminators are rate-based
or ratio-based** — futex rate for `lock-contention-futex-storm`, syscall volume shifts, request
counts. This is direct, published evidence that **rate is a noisy feature between containers that
should behave identically**, and that **process-structure features are the stable ones**.

**This is a hypothesis to test on our data, not a correction to make.** Our comparison is
different from theirs in a way that may save us: we compare a container **against its own
baseline window in the same run**, not against a sibling replica. Same process, same machine, same
minute — which removes most of the "varying workloads, network conditions, user behavior" they
blame. **The check worth running is whether our fault-window ratios exceed the natural
window-to-window variation of the same container under no fault.** If our thresholds are inside
that band for any family, the finding is noise. We have the data to answer this.

**Their 30-second interval and their "longer intervals give greater similarity" finding bear
directly on our window scoring.** Our IoU metric rewards tight windows; their measurement says
**short windows are noisier**. There is a real tension between *earliness* and *stability* and
they quantified one side of it.

**A second axis we do not have.** Their whole method needs **replicas**. Sock Shop as we deploy it
runs **one instance per service**, so REPLICAWATCHER's approach is unavailable to us — and
usefully so, because it marks a genuinely different way to solve the same problem. **If a reviewer
asks why we do not compare against replicas, the answer is that our deployment has none**, and
that is worth stating explicitly rather than being asked.

**Their normality-drift finding is an argument for our labelled dataset.** *"Almost every new
version generates one previously unseen syscall"*, and their example is `getrlimit` appearing
because a .NET SDK patch version changed. **Any baseline learned from one build is stale after the
next deploy.** Our dataset pins submodule SHAs and image builds precisely so this cannot happen
mid-campaign — and this paper is the measurement of what happens when it does.

**One honest comparison point on evaluation scale.** 15,000 normal and 3,750 attack snapshots over
six days, 13 scenarios. Our v2 is 303 runs across 24 families. **Different units** — theirs are
30-second snapshots, ours are full runs with injected windows — so **the counts are not
comparable** and we should not place them side by side.

**And a difference in what is being detected.** Their attacks are **adversarial CVE exploits**;
ours are **performance faults**. Their own weak cases are instructive: they struggle exactly where
the attack *"introduces only subtle variance among replicas"* — i.e. where the fault barely
perturbs behaviour. That is the whole population our dataset is made of.

---

## 9. Safe claims

- Anomaly-detection baselines **age and lose effectiveness**, and microservice environments
  redefine "normality" frequently, so training-based detectors need periodic retraining.
- **Almost every new version of the GOB `cart` microservice, across ten versions over nine months,
  generated one previously unseen syscall.** The 0.6.0 → 0.7.0 upgrade introduced **`getrlimit`**
  after a .NET SDK and gRPC health-probe bump.
- **Netflix makes hundreds of production changes per day** (their citation).
- Key insight: **replicas run identical tasks and exhibit similar behaviour, so a compromised
  replica deviates from its siblings** — no training required.
- **Feature study result: syscall frequency, network IP addresses and ports, latency, delta time
  and buffer length show substantial dissimilarity across replicas; all process-based features
  show little to none.** They select features with **maximum dissimilarity below 0.2** at a
  **30-second interval**, and note **longer intervals give greater similarity**.
- Kernel events captured with **Sysdig plus a custom Chisel**, as a privileged DaemonSet on
  worker nodes.
- Evaluated on a **7-microservice homebrew e-commerce app** and **Google Online Boutique (11
  microservices)**, **13 attack scenarios** from real CVEs including ShellShock (CVE-2014-6271),
  CouchDB RCE (CVE-2022-24706) and path traversal (CVE-2019-5418).
- Two-node GKE cluster, `e2-standard-4`; **2 to 6 replicas** per microservice; 30-50 benign users
  plus one attacker. **15,000 normal and 3,750 attack snapshots, six days of monitoring**, 30 s
  per snapshot.
- **Average AUC 0.9960 (GOB) and 0.9827 (homebrew)**; at uniform threshold ε = 0.3, **precision
  0.9248, recall 0.9813** (abstract: 91.08% / 98.35%).
- **Holds performance across base-OS, dependency and application-code updates where STIDE-BoSC,
  CHIDS and CDL degrade.**
- Scales **sublinearly**; **48 pods classified in under 2.25 seconds**, a density they say matches
  the real-world median.
- Limitations the authors state: **authentication bypass attacks**; lower precision where attacks
  resemble normal noise; lower recall on path traversal, which *"introduces only subtle variance
  among replicas"*.

## 10. Do NOT claim

- That it works without replicas. **Replica comparison is the entire method.** Sock Shop as we
  deploy it has one instance per service.
- That it detects performance faults. Every scenario is an **adversarial CVE exploit**.
- That 91.08% / 98.35% are optimal. They come from a **deliberately uniform threshold** chosen for
  generality; the authors say per-scenario tuning does better.
- That it localises a root cause. The output is **which replica is anomalous**.
- That its snapshot counts are comparable to our run counts. A snapshot is **30 seconds**; our
  unit is a full labelled run.

## 11. Reusable ideas

- **Measure which features are stable before choosing any.** Ranking every candidate by
  dissimilarity under normal operation, then keeping only those under 0.2, is a discipline our
  blueprints do not currently apply — and their answer (rates are noisy, process structure is
  stable) is testable on our data.
- **Remove the baseline instead of refreshing it.** When "normal" drifts faster than you can
  retrain, compare against something that drifts with you.
- **Evaluate before and after an update, not just once.** Their contribution is only visible in
  the post-update comparison; a single-point evaluation would have shown four similar systems.
- **Report the window-length trade-off.** Longer intervals are more stable; they said so and
  picked a number. Our IoU scoring has the same tension between earliness and stability.
- **Name the attacks you cannot catch.** Authentication bypass, path traversal with subtle
  variance — stated plainly, which is what makes the rest credible.
