# Paper Context: Multi-level Host-based Intrusion Detection System for Internet of Things (Journal of Cloud Computing 2020)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> Cited for the **data-exfiltration** blueprint and listed under `resource_abuse`. It is **the
> closest paper in the pack to our collection setup** — LTTng, kernel tracepoints, a published
> tracepoint list, and overhead measured the way ours is. **Its 100% accuracy is not what it
> looks like**; see §8, which explains why and why that is useful to us anyway.

---

## 1. Bibliographic info

- **Title:** Multi-level host-based intrusion detection system for Internet of things
- **Authors:** Robin Gassais, Jose M. Fernandez, Daniel Aloise, Michel R. Dagenais
  (Polytechnique Montréal); **Naser Ezzati-Jivan** (Brock University, corresponding author)
- **Venue:** *Journal of Cloud Computing: Advances, Systems and Applications* **9:62, 2020**
- **DOI:** 10.1186/s13677-020-00206-6
- **Open access.**

```bibtex
@article{gassais2020multi,
  title   = {Multi-level host-based intrusion detection system for Internet of things},
  author  = {Gassais, Robin and Ezzati-Jivan, Naser and Fernandez, Jose M. and Aloise, Daniel and Dagenais, Michel R.},
  journal = {Journal of Cloud Computing}, volume = {9}, number = {62}, year = {2020},
  doi     = {10.1186/s13677-020-00206-6}
}
```

Same lab as Giraldeau, Nemati, Kohyarnejadfard and Gelle — the DORSAL group plus Brock.

---

## 2. One-paragraph summary

Most IoT intrusion detection is **network-based**, and the authors' starting point is that *"on
many systems, intrusions cannot easily or reliably be detected from network traces."* So they go
**host-based**: trace the device with **LTTng**, combining **syscalls, network events, scheduler
events, CPU events and kernel-module events**, turn each event into a numeric feature vector, and
train classifiers to flag intrusions. They test on a **real home-automation controller (a
Raspberry Pi 3)** against **seven real attacks** including a Mirai-style infection, an nmap scan,
a Metasploit Hail Mary, a ransomware and a custom spying tool. **Tree-based models reach 99.97% to
100%; neural networks and SVM fail badly.** Tracing overhead is **0.25% to 1.52%** depending on
snapshot frequency.

---

## 3. Why host-based, and the threat taxonomy

Their framing: vendors ship fast and secure later, devices are heterogeneous and resource-poor,
and network-based detection is defeated by obfuscation — they cite Homoliak et al. that
*"obfuscation of TCP communication can reduce the chance of detection significantly."*

Their five IoT threat categories, adapted from Babar et al.:

| Threat | What the attacker wants |
|---|---|
| **Data exfiltration** | eavesdropping, information theft, or inference — obtain confidential information |
| **Data alteration** | inject false data or commands; replay or person-in-the-middle; change system behaviour |
| **Denial of service** | make the system unreachable — either bricking the device (Brickerbot) or using it against a remote target (Mirai) |
| **Intrusion inside a network** | use a home controller as a foothold past the external firewall |
| **Physical security** | a controlled oven and gas valve; pacemakers; remotely controlled cars |

**Our `data_exfiltration` fault sits in the first category and our `resource_abuse` in the third**,
under the "device used against a remote target" reading.

---

## 4. Why they chose LTTng — the argument is ours too

- **Very low overhead**, and easy to enable or disable tracepoints; recent releases can even
  **filter at the tracepoint**.
- Writes **CTF**.
- *"LTTng is able to get multi-level information on the system, such as syscalls, scheduler
  events, user-space events, network events, and some hardware information."*
- Easy to port to new embedded architectures; only requires Linux.
- The user specifies **which tracepoints to monitor and how often** to receive snapshots.

**They collect in snapshots**, sent at a configurable interval — 30 seconds for the benign phase,
1 second under attack.

---

## 5. Their tracepoint list — worth comparing against ours

Published in full in their Table 2.

| Category | Tracepoints |
|---|---|
| **Scheduler** | `sched_switch`, `sched_process_fork`, `sched_process_exec`, `sched_process_exit` |
| **Network** | `net_dev_queue` |
| **Kernel module** | `module_load` |
| **CPU** | **`power_cpu_frequency`** |
| **Syscalls** | ~110 of them |

The syscall set is worth reading, because it is a **security** selection rather than a performance
one. It is heavy on:

- **process and privilege**: `clone`, `fork`, `vfork`, `execve`, `execveat`, `setuid`, `setgid`,
  `setresuid`, `setreuid`, `setgroups`, `setns`, `unshare`, `capset`-adjacent calls, `kill`,
  `tgkill`
- **filesystem and permissions**: `open`, `openat`, `creat`, `chmod`, `fchmod`, `chown`, `chroot`,
  `pivot_root`, `mount`, `umount`, `link`, `symlink`, `unlink`, `rename`, `setxattr`
- **module loading**: `delete_module`, `finit_module`, `kexec_load`, `kexec_file_load`
- **network**: `socket`, `connect`, `listen`, `setsockopt`, `shutdown`
- **identity probing**: `getpid`, `getppid`, `getuid`, `geteuid`, `getcwd`, `getcpu`, `getdents`

**Note what is absent:** no `futex`, no `mm_*`, no block-layer events, no `net_dev_xmit` or
`net_if_receive_skb`. Their network view is **one queue-level tracepoint**. This is an
**attribution-and-behaviour** profile, not a performance one.

---

## 6. The attacks

Seven, all run on a real device:

1. **Mirai-style infection** — built from the GitHub source. Infected devices brute-force default
   passwords, then `wget` a payload via busybox, rename it, `chmod` it, and run it. They replaced
   the payload with one that just echoes "Infected", because **only the infection phase was to be
   traced**.
2. **nmap scan** of the TCP/IP network.
3. **Metasploit Hail Mary** — many exploits at once. **It failed** (the system was patched), but
   the traces of the *attempt* were used.
4. **Directory listing** with DirBuster against the web interface.
5. **Vulnerability scan** with Nikto. **Found nothing**, traces still used.
6. **Ransomware** — AES-256-ECB encryption of a directory. **Only the encryption phase traced.**
7. **A custom spying tool** — records everything sent to the controller's API and resends it to an
   external server. They note it *"does not change the device behavior much, unlike the other
   intrusions."*

**Attack 7 is our `data_exfiltration` fault.** And their own remark about it is the important
part: it is the quiet one.

---

## 7. Setup, labelling, and results

- **Device: Raspberry Pi 3**, ARM, chosen because it has *"the exact same hardware
  characteristics as the HomeSeer HomeTroller Zee S2"*, a real commercial controller.
- **Benign phase: one hour** of ordinary use — switch a light over Z-Wave, power a smart plug,
  trigger a motion sensor — snapshots every 30 s.
- **Attack phase:** a fresh tracing session per attack, snapshots every 1 s.
- **Resulting dataset: 58% benign, 42% intrusion-related events.** They **undersampled** frequent
  events to balance it, and cite the known risk that undersampling naturally imbalanced
  intrusion data introduces bias.
- 66/34 train/test split, **k-fold cross-validation**, grid search for hyper-parameters.

### Labelling — read this before quoting any accuracy

> *"To label those events, we compared each with our database. **Whenever the information of the
> event is already in the database, we remove the event. The events that do not match the database
> are labeled as intrusions.**"*

**Labels are assigned by novelty against the benign trace**, not by independent ground truth.

### Detection results (Table 6, test set, averaged over five folds)

| Model | Accuracy | F1 | Precision | Recall |
|---|---|---|---|---|
| **Gradient Boosted Trees** | **100%** | 99.99% | 99.99% | 99.99% |
| **Random Forest** | **99.99%** | 99.99% | 99.99% | 99.99% |
| **Decision Tree** | **99.97%** | 99.96% | 99.98% | 99.93% |
| MultiLayer Perceptron | **57.85%** | 23.07% | 46.78% | 27.25% |
| SVM | **53.32%** | 99.99% | **47.33%** | 99.99% |

**Their own explanation for the split**, and it is a good one: each field of an event is a
feature, and **events have very different fields** — a syscall event and a network event do not
share a schema. Trees are robust to that; MLP and SVM are not. They deliberately did **not**
normalise or drop fields, because *"it is essential to know the origin of the intrusion to have an
adapted response."*

**The SVM row is worth reading properly: 99.99% recall with 47.33% precision is a classifier that
says "intrusion" to almost everything.** Its F1 of 99.99% in their table is inconsistent with a
precision of 47.33% — F1 cannot exceed either component. **Treat the SVM F1 cell as an error and
do not quote it.**

### Cost

**Tracing overhead**, by snapshot frequency:

| Snapshot interval | Total time | 95th percentile |
|---|---|---|
| 0.5 s | **+1.52%** | +7.49% |
| 1 s | +1.15% | +6.28% |
| 2 s | +0.80% | +4.78% |
| 5 s | +0.39% | +2.21% |
| 10 s | **+0.25%** | +1.24% |

A second measurement on another application gives **+1.82% to +2.73%** across the same range.

**Training and classification cost:** the MLP took **8×** the training time of the trees; **GBT
took more than 6,000×**. At prediction time, **GBT is ~7.5× slower per event than the decision
tree** for a marginal accuracy gain.

They also note the obvious limitation: trees, forests and GBT **cannot detect intrusions they have
not been trained on**, unlike One-Class SVM.

---

## 8. What this means for our work

**This is the closest paper in the pack to our data collection, and it should be cited that way.**
Same tracer, same event categories, same CTF, same lab, on a real device with real attacks — and
it publishes **the exact tracepoint list**, which almost no paper does. When we justify collecting
scheduler plus syscall plus network events together, this is the precedent.

**One concrete confirmation for our own profile.** They enable **`power_cpu_frequency`**, which is
in our v2 profile too. Our CLAUDE.md records that we added it after measuring it was available;
this is independent evidence that it is worth having in a security-adjacent profile.

**Their syscall list is a ready-made starting point for `data_exfiltration` and `fd_exhaustion`.**
It is security-shaped where ours is performance-shaped, and the overlap is smaller than expected.
If we want to strengthen the exfiltration blueprint, **the process/privilege and
filesystem/permission groups are the ones to consider adding** — `execve`, `chmod`, `setuid`,
`connect`, `setsockopt`, `finit_module`. **This is a suggestion to measure, not a change to
make.**

### Why the 100% must not be quoted as a detection rate

**Their labels are generated by novelty against the benign trace.** An event not seen in one hour
of ordinary use is labelled an intrusion; the classifier then learns to separate exactly that. The
99.97-100% is close to **measuring the consistency of the labelling procedure**, not the
difficulty of the task. Two of their own design choices show it:

- The **Hail Mary and the Nikto scan both failed** — nothing was exploited. The "intrusion" events
  are the traces of an *attempt*, which are trivially novel.
- The **Mirai payload was replaced with an echo**, so what is detected is the download-chmod-exec
  sequence, not mining or DDoS behaviour.

**None of that makes the paper wrong.** It makes it a demonstration that *host-level tracing
carries the signal*, which is all we need it for. But **citing "100% accuracy on IoT intrusion
detection" would misrepresent it**, and our `data-exfiltration` blueprint must not lean on that
number.

**The genuinely transferable warning is about our own scoring.** Their attack phase was traced in
a **separate session** from the benign phase, one attack at a time. That is the same structure as
our per-run fault injection, and it carries the same risk: **anything that differs between the two
sessions becomes "the fault"** — start-up effects, a different time of day, a cold cache. Our
scorer compares against ground truth rather than against a benign trace, which avoids the worst of
it, but the `code_*` families are injected by restarting a service, and that is worth checking.

**Their spying tool is the honest note for our exfiltration fault.** *"It does not change the
device behavior much, unlike the other intrusions."* That is exactly why exfiltration is hard and
why it is worth a blueprint — and it means any signature we find should be checked against a
**plausible benign transfer**, not only against idle.

**One model result to put beside Karn et al.** Trees beat neural networks decisively here too,
and for a stated structural reason: **heterogeneous event schemas**. Karn found the same on
syscall n-grams. Two papers, same lab lineage in one case and none in the other, same conclusion.
Evidence that our rule-based blueprints are not a compromise on this kind of data.

**Overhead comparison, with the caveat attached.** Their **0.25-1.52%** is for **snapshot-mode
LTTng on a Raspberry Pi with ~115 tracepoints**. Ours is **continuous full-kernel collection on a
12-core VM at 1.56M events/s**. The numbers are not comparable and we should never place them side
by side without saying which is which.

---

## 9. Safe claims

- Most IoT intrusion detection is network-based, but *"on many systems, intrusions cannot easily
  or reliably be detected from network traces"*, and **obfuscation of TCP communication
  significantly reduces the chance of network detection**.
- Their IoT threat taxonomy: **data exfiltration, data alteration, denial of service, intrusion
  inside a network, physical security**.
- They use **LTTng** for its low overhead, CTF output, easy tracepoint enable/disable, tracepoint
  filtering, portability to embedded architectures, and its ability to collect **syscalls,
  scheduler events, user-space events, network events and some hardware information** together.
- **Published tracepoint list**: `sched_switch`, `sched_process_fork/exec/exit`, `net_dev_queue`,
  `module_load`, **`power_cpu_frequency`**, and ~110 syscalls weighted towards process,
  privilege, filesystem, module-loading and network operations.
- Seven real attacks on a **Raspberry Pi 3** home-automation controller with the same hardware as
  a commercial HomeSeer unit: Mirai-style infection, nmap scan, Metasploit Hail Mary, DirBuster
  directory listing, Nikto vulnerability scan, AES-256 ransomware, and a **custom spying tool**.
- The Hail Mary and Nikto scans **did not succeed**; only the attempt was traced. The Mirai
  payload was **replaced with an echo**, tracing only the infection phase. The ransomware was
  traced only during **encryption**.
- Dataset: one hour benign at 30 s snapshots, attacks at 1 s snapshots, **58% benign / 42%
  intrusion**, **undersampled** to balance — with the authors noting undersampling can bias
  naturally imbalanced intrusion data.
- **Labels were assigned by novelty**: events matching the benign database were removed, and
  non-matching events labelled as intrusions.
- **GBT 100%, Random Forest 99.99%, Decision Tree 99.97% accuracy; MLP 57.85%, SVM 53.32%.**
  The authors attribute the failure of MLP and SVM to **heterogeneous event field schemas**, which
  trees tolerate.
- Tracing overhead **+0.25% (10 s snapshots) to +1.52% (0.5 s)** on total time, 95th percentile
  +1.24% to +7.49%; a second application gave +1.82% to +2.73%.
- **GBT training took over 6,000× the decision tree's**, and its per-event prediction is **~7.5×
  slower**.
- Tree-based models **cannot detect intrusions they have not been trained on**; One-Class SVM can.
- Their spying tool *"does not change the device behavior much, unlike the other intrusions."*

## 10. Do NOT claim

- **That it achieves 100% intrusion detection accuracy in any meaningful sense.** Labels were
  generated by novelty against a one-hour benign trace, two of the seven attacks did not succeed,
  and the Mirai payload was replaced with an echo. It demonstrates that the signal is present in
  host traces; it does not measure detection difficulty.
- The SVM's **F1 of 99.99%**. It is inconsistent with the reported precision of 47.33% and appears
  to be a table error.
- That it applies to microservices or containers. The subject is a **single IoT device**.
- That its overhead is comparable to ours. It is **snapshot-mode tracing of ~115 tracepoints on a
  Raspberry Pi**, not continuous full-kernel collection.
- That it localises anything. The output is a **binary intrusion label per event**.

## 11. Reusable ideas

- **Publish the tracepoint list.** Almost nobody does, and it is the single most reusable artefact
  in the paper.
- **Keep the raw event fields.** Their refusal to normalise away the source IP — *"it is essential
  to know the origin of the intrusion"* — is the same instinct as our WHERE axis, and it is what
  broke the neural models.
- **Heterogeneous schemas favour trees.** A structural reason, not a tuning accident, and it now
  has two independent confirmations in our reference set.
- **Report the cost of the best model.** 6,000× training time for a fraction of a percent is the
  kind of trade-off that should be visible.
- **Trace the attempt, not only the success.** Their Hail Mary and Nikto found nothing and were
  still useful data. Our equivalent is that a fault that fails to degrade anything still produces
  a trace worth keeping.
