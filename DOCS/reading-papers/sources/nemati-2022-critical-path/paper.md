# Paper Context: Critical Path Analysis through Hierarchical Distributed Virtualized Environments Using Host Kernel Tracing

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
>
> **What is actually on disk.** The IEEE TCC article is paywalled. The PDF here is the first
> author's **173-page PhD thesis** (Nemati, Polytechnique Montreal, 2019), which is
> article-based. **The paper we cite is Chapter 5**, pp. 71-108. This summary covers the thesis
> abstract, Chapter 5 in full, and the thesis contributions. Chapters 4 and 6 are other
> articles and are summarised only in passing.
>
> Read §9 before citing. The single most relevant thing here is the **event list** - and two of
> its seven events are ones we do not collect.

---

## 1. Bibliographic info

- **Article (what we cite):** Nemati, H., Tetreault, F., Puncher, J., Dagenais, M. R.
  "Critical Path Analysis through Hierarchical Distributed Virtualized Environments Using Host
  Kernel Tracing." **IEEE Transactions on Cloud Computing**, vol. 10, pp. 774-791, 2022.
- **Thesis (the file on disk):** Hani Nemati, *Virtual Machine Flow Analysis Using Host Kernel
  Tracing*, PhD thesis, Polytechnique Montreal, 2019. 173 pp.
  https://publications.polymtl.ca/3902/1/2019_HaniNemati.pdf
- Chapter 5 is marked in the thesis as **"Submitted to IEEE Transactions on Cloud Computing…
  Under-Review"**, so the thesis version predates the published article.

```bibtex
@article{nemati2022critical,
  title   = {Critical Path Analysis through Hierarchical Distributed Virtualized Environments Using Host Kernel Tracing},
  author  = {Nemati, Hani and Tetreault, Francois and Puncher, Jason and Dagenais, Michel R.},
  journal = {IEEE Transactions on Cloud Computing}, volume = {10}, pages = {774--791}, year = {2022}
}
```

---

## 2. One-paragraph summary

A cloud provider cannot install a tracing agent inside a customer's VM. This work recovers what
is happening **inside** VMs - process states, why a process is waiting, and the chain of
wait/wake dependencies - by tracing **only the host hypervisor**. It works at arbitrary nesting
depth, so a VM running its own VMs is still visible. Three algorithms do it: **ASD** finds vCPU
states, **GTA** finds thread and process states inside the guest, and **HEC** builds the
execution graph and extracts the critical path across VMs and across the network. Measured
overhead is **about 0.3%**, against **3.65-6.13%** for the approach that traces each VM.

---

## 3. Why host-only tracing

Their argument, which is the most transferable part of the paper:

- **The provider has no access to client VMs** to install an agent.
- Tracing every layer produces **redundant data** and much higher overhead than host-only.
- Three further cases where in-guest tracing is simply impossible:
  1. the VM kernel is too old for modern tracing tools;
  2. the VM kernel is **closed-source** with no tracer available;
  3. the VM does not have enough resources to run a tracer properly.

They also frame the diagnostic problem cleanly. Performance degradation in a VM has four
possible causes: **(a)** heavy load inside the VM, **(b)** contention with other applications
inside the VM, **(c)** contention with **other co-located VMs**, **(d)** cloud platform
failures. The first two are the VM owner's problem; **the last two are the provider's**, and
only the provider can see them.

---

## 4. The core idea: the wake-up reason names the wait

A process waits in one of four ways, and **the interrupt that wakes it identifies which**:

| Woken by | Meaning |
|---|---|
| **Timer interrupt** | a timer fired inside the VM |
| **IPI / another process** | it was waiting for another process to finish |
| **Network interrupt** | it was waiting for an incoming packet |
| **Disk interrupt** | it was waiting for block I/O |

Anything else becomes `wait_for_other`. This is Giraldeau's principle applied through the
virtualisation boundary: **the cause of an idle state is unknown a priori and the wake-up event
reveals it.**

The mechanism that makes it work across the boundary is **virtual interrupt injection**. When
an interrupt arrives, the CPU exits the VM, the VMM injects a `virq` by emulating the LAPIC,
and the guest handles it on resume. So `kvm_inj_virq` with its vector number is what tells the
host *why* a guest process woke up.

---

## 5. Virtualisation background the paper relies on

- Intel VT provides **VMX root** (hypervisor) and **VMX non-root** (guest) modes. Transitions
  are **VM Entry** and **VM Exit**, controlled by the **VMCS** structure, one per vCPU.
- For **nested** VMs there are **three VMCS structures per vCPU**: host↔L1, L1↔L2, and
  host↔L2.
- Any privileged instruction in L2 traps to **L0**, the host hypervisor. L1 has the illusion
  of running L2 directly on physical CPU.
- Process states: running alternates between VMX root and non-root. Waiting splits into
  **Preempted** (the pCPU was taken away and given to something else, possibly another VM's
  vCPU) and **wait_for_X** (the guest voluntarily yielded with `hlt`).

That Preempted/wait_for distinction is the same one our blueprints make between *runnable but
not running* and *blocked*.

---

## 6. The three algorithms

- **ASD — Any-Level vCPU States Detection.** Works out vCPU state at any nesting depth from
  host events. They contrast it with a naive **Entry-Exit Algorithm (2EA)** using only
  `sched_in`, `sched_out`, `vm_enter`, `vm_exit`: 2EA shows a vCPU as simply "Idle" between two
  times **with no reason**. ASD adds `inj_virq` and reads the **vector number** to name the
  reason - vec0 disk, vec1 task, vec2 net, vec3 timer.
- **GTA — Guest (Any Level) Thread-state Analysis.** Recovers per-process and per-thread states
  inside guests, including nested ones. Processes are distinguished by the **CR3** register
  value in the `vm_enter` payload.
- **HEC — Host-based Execution-graph Construction.** Builds the dependency graph and extracts
  the active path across VMs and across the network.

---

## 7. Events required (their Table 5.3)

| Category | Event | LTTng event | Method |
|---|---|---|---|
| scheduler | `sched_switch` | `sched_switch` | tracepoint |
| scheduler | `wake_ttwu` | `sched_ttwup` | tracepoint |
| hypervisor | `vm_exit` | `kvm_exit` | tracepoint |
| hypervisor | `vm_inj_virq` | `kvm_inj_virq` | tracepoint |
| hypervisor | `vm_entry` | `kvm_entry` | tracepoint |
| hypervisor | `vcpu_enter_guest` | — | **kprobe** |
| network | `inet_sock_in` | `inet_sock_local_in` | **netfilter** |
| network | `inet_sock_out` | `inet_sock_local_out` | **netfilter** |

---

## 8. Evaluation

- **Setup:** LTTng v2.8 on host, guest and nested VM; Qemu/KVM; Trace Compass for analysis.
- **Workloads:** Hadoop TeraSort (50 GB, 3 VMs, 3 vCPUs and 3 GB each), Apache, MySQL, Linux
  `apt-get`, and an **IMS network** - the last drawn from industry.
- **Overhead (their Table 5.8),** HEC (host-only) versus CPA (tracing each VM):

| Benchmark | CPA overhead | **HEC overhead** |
|---|---|---|
| File I/O | 6.13% | **0.03%** |
| Memory | 4.81% | **0.01%** |
| CPU | 3.65% | **0.30%** |

Their summary: **~0.3% for HEC, 3.65-6.13% for approaches that trace inside the VMs.**

They also note CPA requires precise **time synchronisation** to be enabled inside the VMs,
which adds further overhead that is not in the table.

---

## 9. What this means for our work

**This is the citation for "diagnose from the host without touching the guest", and it is a
good one.** The reference pack uses it to support our pid-namespace attribution: we read
container behaviour from host-level kernel events without instrumenting any service. That maps
directly onto their argument, and their four-cause framing (load / in-VM contention /
**co-tenant contention** / platform failure) is a clean way to motivate blueprint 7.

**But the event set does not match ours, and two gaps matter:**

| They need | We have | Consequence |
|---|---|---|
| `sched_ttwup` (wake-up **with source**) | `sched_wakeup` | Same gap as Giraldeau. We see that a wake happened, not reliably *who* did it |
| `kvm_exit`, `kvm_entry`, `kvm_inj_virq`, `vcpu_enter_guest` kprobe | **none** | We have no hypervisor layer at all |
| `inet_sock_local_in/out` via netfilter | `net_dev_xmit`, `net_if_receive_skb` | device-level, not socket-level |

**The hypervisor gap is not a weakness for us - it is a scope difference.** Their whole problem
is seeing *through* a virtualisation boundary. We run containers on one host, sharing one
kernel, so there is no boundary to see through: `pid_ns` is directly in our events. Their
machinery is solving a problem we do not have.

**So cite it for the principle, not the method.** Safe: *host-level tracing is sufficient to
attribute behaviour to isolated workloads without instrumenting them.* Not safe: *we implement
critical-path analysis across virtualisation layers.*

**The overhead numbers are the most directly usable thing.** 0.3% host-only versus 3.65-6.13%
in-guest is a clean, quotable comparison for why host-level collection is the right choice -
and it is measured, not asserted. Our own collection overhead should be reported against this.

**One methodological detail worth copying.** Their contrast between **2EA** and **ASD** is
exactly the argument our blueprints make: a naive analysis shows a container as "idle" and
stops there; adding one more event class turns "idle" into "waiting for disk". That is the
same move as our discriminators, and it is a good way to explain to a reviewer why the extra
events earn their cost.

---

## 10. Safe claims

- Host-only hypervisor tracing can recover vCPU, process and thread states inside VMs, and at
  arbitrary nesting depth, **without any agent in the guest**.
- The reason a guest process was waiting is revealed by the **injected virtual interrupt
  vector** - disk, task/IPI, network, or timer.
- Cloud providers generally cannot install tracing agents in client VMs; tracing every layer is
  redundant and far more expensive.
- Three further cases block in-guest tracing: kernel too old, kernel closed-source, or the VM
  lacks resources to run a tracer.
- Performance degradation in a VM has four causes - in-VM load, in-VM contention, **co-located
  VM contention**, and platform failure - and the last two are only visible to the provider.
- **Measured overhead ~0.3% for host-only tracing, against 3.65-6.13% for in-VM tracing**
  (File I/O 0.03% vs 6.13%, Memory 0.01% vs 4.81%, CPU 0.30% vs 3.65%).
- Nested virtualisation uses three VMCS structures per vCPU; any privileged instruction in L2
  traps to L0.
- Evaluated on Hadoop TeraSort, Apache, MySQL, `apt-get`, and an IMS network.
- Implemented as Trace Compass modules and open-sourced.

## 11. Do NOT claim

- That the file on disk is the IEEE TCC article. **It is the author's PhD thesis**; the article
  is paywalled. Cite the article by DOI, and note the thesis as the accessible version.
- That we reproduce this method. We have **no** hypervisor events, no `kvm_*` tracepoints, and
  no nested virtualisation.
- That 0.3% is our overhead. It is theirs, on their event set, on KVM.
- That `sched_ttwup` and `sched_wakeup` are interchangeable. The source of the wake-up is the
  point.

## 12. Reusable ideas

- **Trace at the boundary you control, not inside what you are observing.** The whole design
  follows from "we cannot touch the guest", and it produces a 10-20× overhead advantage.
- **The wake-up vector names the wait.** One event class turns "idle" into a reason.
- **Show the naive algorithm first.** 2EA versus ASD makes the contribution obvious in one
  figure.
- **Separate what the tenant can fix from what the operator can fix.** Their four-cause split
  is a useful frame for reporting a diagnosis, not just producing one.
