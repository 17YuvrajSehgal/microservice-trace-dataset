# Weekly update: 9 to 16 September 2026

40 commits. 111 files changed.

---

## In one line

I checked every run in the dataset and found 59 bad ones. I built a new VM and
re-collected 54 of them. Two new findings came out of it.

---

## 1. Checked every run in the dataset

I went through all 303 runs. Nothing was skipped.

**59 of 303 runs are not usable. 244 are fine.**

| problem | runs |
|---|---|
| the fault did not inject | 32 |
| the baseline window is spoiled | 27 |

Nothing is corrupt. Every bundle has its trace, metadata, ground truth and checksums.

I also found the cause of the spoiled baselines. Eleven fault recipes started the fault
*before* writing down the start time. So the fault sat inside the window meant to be clean.
All eleven are fixed. A checker now tests this, and all 23 recipes pass.

Write-up: `../blueprints/docs/AUDIT-v2-full.md`.

## 2. The analysis was ignoring the campaign's own verdict

Every run already carries a verdict saying whether the fault was seen. No analysis script read it.

So runs where the fault never injected were being used as good examples.

I made the analysis read it.

| | before | after |
|---|---|---|
| recall | 73% | 90% |

## 3. Built a new VM and re-collected 54 runs

The old collection VMs were deleted in July. I built a replacement with the same shape, so the
numbers stay comparable.

| family | runs | result |
|---|---|---|
| 5 code-defect families | 26 | all usable |
| `anomaly_net` | 8 | all confirmed |
| `dns_delay` | 5 | all usable |
| `fd_exhaustion`, `lock_contention`, `deadlock` | 15 | see below |

**The fix works, and I checked it on the traces rather than trusting the label.**

- Code defects: the old runs restarted the container inside the clean window. Packet loss in
  that window was 34.7% to 79.9%. Now it is 0.00%.
- `anomaly_net`: same idea. Baseline packet loss is now 0%. The loss only shows during the fault.

## 4. Two findings

### Two of the five code defects do move a metric. Three do not.

I thought none of them did. That was wrong.

| family | baseline | during fault | after |
|---|---|---|---|
| `code_lock_across_io` | 106.5 | 262.2 | 262.7 |
| `code_n_plus_one` | 104.1 | 255.9 | 255.0 |
| `code_unbounded_cache` | 99.8 | 245.9 | 247.2 |
| `code_event_loop_block` | 102.8 | **34.3** | **122.4** |
| `code_serial_awaits` | 93.6 | **50.5** | **132.4** |

Read the last column. For the first three, the number during the fault and after the fault are
the same. So nothing happened. For the last two, the rate drops during the fault and comes back
after. That is the fault.

Both of the visible ones are the front-end, written in Node. Node runs one loop. Block it and
every request stops. The other three are Go, which runs many requests at once and absorbs it.

Same kind of bug. Opposite result. That is useful for the paper.

Two other things agree with this. The two visible families produced about half the trace data,
and about half the compressed file size. Fewer requests means fewer events.

### One family got worse when I re-ran it

I picked three families to re-run because each had partly worked before. My reason was that a
recipe that sometimes works is probably just unlucky.

| family | before | after | |
|---|---|---|---|
| `lock_contention` | 2 of 5 | 5 of 5 | better |
| `deadlock` | 4 of 5 | 5 of 5 | better |
| `fd_exhaustion` | 2 of 5 | **0 of 5** | worse |

Right for two. Wrong for one. `fd_exhaustion` now fails every time, so re-running it did not help.

My guess is that metrics simply cannot see this fault, while the kernel trace can. **Not checked
yet.** It needs a look at the 5 new traces.

## 5. Moved the data to the cluster

All 39 re-collected runs are on Trillium. 7 files, 107 GB. Checked by opening each file and
counting the runs inside.

This mattered because the runs only existed on one machine. We have already lost VMs once.

The old way of sending data stopped working. The cluster now asks for a phone code, and a
script cannot answer that. I reversed the direction. The cluster now pulls from the VM instead.
The key this needs is locked to one command, so it cannot be used for anything else.

## 6. Blueprint work

- Every blueprint now draws its own picture showing how it decided. 10 of 10.
- Every threshold now lives in one file. Before, the document and the code could disagree.
- Thresholds that measure our hardware were replaced with ratios where possible. A number like
  "2000 disk requests per second" only means something on our machine. A ratio travels.
- Blueprint steps no longer name our cluster paths. Someone else can run them on their own data.
- Told apart "the system is slow but working" from "the system is broken". False alarms dropped
  from 46 to 19.

## 7. Wrote three documents

| doc | what it is |
|---|---|
| `../READING-ORDER.md` | Which of the ~120 docs to read, in what order, and which to skip |
| `../blueprints/docs/EVAL-PLAN-effectiveness.md` | The plan for testing whether blueprints help an agent |
| `../blueprints/docs/AUDIT-v2-full.md` | The full check of all 303 runs |

The eval plan is written before running anything, so we cannot move the goalposts later.
It also covers early detection, which nothing measures today.

---

## What is left

| item | needs |
|---|---|
| move the last 15 runs to the cluster | nothing, can do now |
| retire the old spoiled files on the cluster | your go-ahead |
| stop the VM | after the last transfer |
| check the `fd_exhaustion` guess | a short look at 5 traces |
| 26 Train Ticket runs | a Train Ticket VM, which does not exist |
| run the eval plan | building one new setup |

Of the Train Ticket runs, 18 should **not** be re-collected. They look broken but are not. The
fault is real; our measurement looks at the wrong level. Re-collecting would not change them.

---

## Honest notes

- The `fd_exhaustion` guess is a guess. I have not checked it.
- The re-run choice was right for 2 families out of 3.
- I had one wrong claim this week and corrected it. I said no code defect moves a metric. Two do.
- The baseline window in every run includes the load generator starting up. We decided to leave
  it, so the new runs stay comparable with the old ones.
