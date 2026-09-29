# How agent v2 works

Three diagrams: the flow, where the data comes from, and how memory works. Written 29-09-2026
against `agent_v2.py`, `ctf_tool.py`, `codetool.py`.

The one-line version: **a planner splits the job, up to four workers investigate in parallel
with their own tools, a reviewer decides whether to go again, and a synthesiser writes the
verdict from the findings the workers chose to record.**

---

## 1. The flow

```mermaid
flowchart TD
    START([one run, one incident]) --> PLAN

    PLAN["<b>PLANNER</b><br/>splits into up to 4 subtasks<br/>one model call, no tools"]
    PLAN -->|Send, one per subtask| W1
    PLAN -->|Send| W2
    PLAN -->|Send| W3
    PLAN -->|Send| W4

    subgraph WORKERS["WORKERS - run in parallel, own message thread each"]
        direction LR
        W1["worker 1<br/>up to 12 tool turns"]
        W2["worker 2"]
        W3["worker 3"]
        W4["worker 4"]
    end

    W1 --> REV
    W2 --> REV
    W3 --> REV
    W4 --> REV

    REV{"<b>REVIEWER</b><br/>is this enough?"}
    REV -->|"needs more - max 1 extra round"| W5["2 follow-up workers"]
    W5 --> REV2{"round budget spent"}
    REV2 --> SYN
    REV -->|enough| SYN

    SYN["<b>SYNTHESISER</b><br/>reads the scratchpad ONLY<br/>calls submit_diagnosis"]
    SYN --> OUT([what / where / when])

    classDef node fill:#e8f0fb,stroke:#2a78d6,color:#10243e
    classDef work fill:#e6f5ef,stroke:#1baf7a,color:#10243e
    classDef out fill:#f0efec,stroke:#6b6b6b,color:#10243e
    class PLAN,REV,REV2,SYN node
    class W1,W2,W3,W4,W5 work
    class START,OUT out
```

**Limits, from the code:** `MAX_SUBTASKS = 4`, `MAX_WORKER_STEPS = 12`, `MAX_ROUNDS = 2`.

The workers never call `submit_diagnosis` — only the synthesiser does. And the synthesiser has
**no tools**: it cannot go and look at anything, it can only weigh what the workers wrote down.
That is deliberate, and it is also where the current bug lives. See section 3.

---

## 2. Where the trace comes in

The agent never touches the 15 GB trace directly. One decode pass turns it into two small files,
and everything the agent can do is a read of those.

```mermaid
flowchart LR
    CTF[("raw LTTng trace<br/><b>15 GB</b> per run")]
    CTF -->|"one decode pass<br/>build_ctf_index.py"| IDX

    subgraph IDX["the index - 15 MB each"]
        direction TB
        TSV["<b>counts</b><br/>bucket, event, procname,<br/>pid_ns, count, value_sum<br/>100 ms buckets"]
        LIN["<b>line sample</b><br/>one raw line per<br/>bucket per event<br/>capped 1200 chars"]
    end

    IDX --> T1
    IDX --> T2
    CTF -.->|"slow path: filtered<br/>ctf_lines re-decodes"| T1

    subgraph TOOLS["what a worker can call"]
        direction TB
        T1["<b>6 registered tools</b><br/>ctf_timespan, ctf_timeline,<br/>query_ctf, ctf_lines,<br/>ctf_procdiff, ctf_proclife"]
        T2["<b>run_python</b><br/>sandboxed, index<br/>pre-loaded as a DataFrame"]
        T3["<b>note_finding</b><br/>writes to the scratchpad"]
    end

    GT[("ground_truth.json<br/>sits INSIDE the run dir")]
    GT -.->|"NEVER reachable"| TOOLS
    GT ==>|"read only here"| SCORE["scorer<br/>q2_judge, nsmap"]

    classDef data fill:#e8f0fb,stroke:#2a78d6,color:#10243e
    classDef tool fill:#e6f5ef,stroke:#1baf7a,color:#10243e
    classDef bad fill:#fbe9e9,stroke:#d03b3b,color:#10243e
    class CTF,TSV,LIN data
    class T1,T2,T3 tool
    class GT,SCORE bad
```

**The ground-truth boundary is the rule the whole harness exists to keep.** `ground_truth.json`
lives in the same directory as the trace, so a tool handed a run path is one `open()` away from
the answer. `run_python` is therefore never given a run path at all — it gets a pre-loaded
DataFrame and no filesystem. The scorer reads ground truth; nothing the agent can call does.

**Two speeds.** Counts come from the index and answer in under a second. A `ctf_lines` call with
a `procname` or `contains` filter cannot be served from a one-line-per-bucket sample, so it falls
back to decoding the trace — 40 to 60 seconds. That is the right trade: slow and correct beats
fast and wrong.

**Every tool result is masked by `leakguard` before the model sees it**, and capped per tool
(`ctf_proclife` 45 KB, `ctf_procdiff` 24 KB, `ctf_lines` 18 KB, others 12 KB). Oversized results
are trimmed by dropping whole rows, never by slicing the JSON, and the model is told what was
dropped.

---

## 3. How memory works

There are three kinds, and they have very different lifetimes. This is the part worth
understanding, because the agent's most persistent failure lives here.

```mermaid
flowchart TD
    subgraph W["inside ONE worker"]
        direction TB
        TH["<b>message thread</b><br/>every tool result, in full"]
        TR["<b>trimmed each turn</b><br/>newest 40 KB of tool output kept<br/>older results replaced by a stub"]
        TH --> TR
    end

    TR -->|"worker ends"| GONE(["thread is DISCARDED"])

    TR -.->|"only if the worker<br/><b>calls note_finding</b>"| SP

    SP["<b>SCRATCHPAD</b><br/>list of findings<br/>claim, where, when,<br/>evidence, confidence"]

    SP --> SYN["SYNTHESISER<br/>sees this and nothing else"]
    SYN --> DX([diagnosis])

    DX -->|"run ends"| NOTHING(["<b>nothing carries to the next run</b><br/>by design - cross-run memory<br/>would leak between incidents"])

    classDef keep fill:#e6f5ef,stroke:#1baf7a,color:#10243e
    classDef lost fill:#fbe9e9,stroke:#d03b3b,color:#10243e
    classDef neutral fill:#e8f0fb,stroke:#2a78d6,color:#10243e
    class SP,SYN keep
    class GONE,NOTHING lost
    class TH,TR,DX neutral
```

### The three kinds

| memory | scope | survives to | why |
|---|---|---|---|
| **message thread** | one worker | nothing | trimmed to 40 KB of tool output per turn, because a thread is re-sent every step and cost grows with the square of the turns |
| **scratchpad** | whole run | the synthesiser | the only thing that crosses the worker boundary |
| **cross-run** | — | **nothing, deliberately** | an agent that remembered incident 1 while diagnosing incident 2 would make later runs easier than earlier ones and break the independence the scores assume |

### The failure this design produces

**Anything a worker computes but does not write down is lost.** The synthesiser has no tools, so
it cannot go back and look.

Measured on the `dependency_outage` smoke run, 29-09. A worker ran exactly the right query:

| pid_ns | baseline/s | incident/s | ratio |
|---|---|---|---|
| **4026532822** | **1242.8** | **0** | **0.00** |
| 4026532751 | 86,597 | 44,477 | 0.51 |

That is the blueprint's deciding test passing exactly as written — lowest at 0.00, next at 0.51.
**It never became a finding.** Zero of nine findings mentioned that namespace, and the
synthesiser answered `normal`.

Two things went wrong at once, and both are properties of this design rather than of the model:

1. **A different worker filtered the answer away and recorded the exclusion as a fact.** It
   restricted to containers above a CPU floor, which excluded the silent container because it is
   small, then wrote the finding *"confirms no near-silent container"*. A tidiness filter became
   a claim the synthesiser had no way to check.
2. **The worker that got it right never called `note_finding`.**

This is the third time the agent has computed a discriminator and not acted on it — `svc_net`
and `svc_cpu_cap` were the first two, and both looked like answer-format problems at the time.

**The fix this points at:** a worker that runs code bearing on the blueprint's deciding test
should be required to record the result, whichever way it came out. Right now recording is
voluntary, and the synthesiser cannot tell the difference between "checked and found nothing"
and "never checked".

---

## What the agent is never told

Worth stating, because it is easy to assume otherwise:

- **not** that anything went wrong
- **not** when the incident was — finding the window is half the task and is scored separately
- **not** which service is the target
- **not** the fault name

It gets a run identifier that has been pseudonymised, the tools above, and — in the `given` arm
— one blueprint.
