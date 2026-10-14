# 14-10-2026

- Mahsa review: 10 suggestions on the workshop paper. Assessed each
  (details in chat): 9 are doable from existing data/wording (several are
  real corrections: the "<1% variation" claim is false - total wall varies
  10-15% from LLM; the io bandwidth numbers mix device/file bytes; >=10ms
  stalls exist below over-subscription; "OS-bound" is overstated since model
  stays 53-71% of wall even at 0.25 core). Only #3 needed new experiments.
- RAN #3 (realistic end-to-end): the REAL coding task (implement: edit code
  + run tests) under memory + disk caps, both agents, total time + success.
  CPU + unlimited reused from Problem 1. Agent coding-task mem peak ~340 MiB
  (mostly reclaimable). Results (E2E-RESULT.md):
  - Claude (node): mem >=192M no effect; 128M -> thrash (6 OOM kills), 7x
    slower, 1/3 success; 96M -> 30x slower, 0/3. Disk 50/20MB/s no effect.
    So ONLY CPU bites a lightweight coding task; memory bites only when the
    cap < the agent's own footprint (~190MiB), disk never (I/O-light).
  - Codex (Rust): survives ALL levels incl 96M (lean). Walls LLM-latency-
    dominated (OpenRouter ~220s, noisy) -> report by outcome not time.
    Reinforces: memory cliff tracks agent footprint (node dies <190M, Rust
    survives <96M).
  - Behavior (#4): two regimes. Tool-OOM -> agent survives + reports correct
    reason, no retry (synthetic 640M). Agent-OOM (128/96M) -> node thrashes,
    repeated kills, dies with empty log, no graceful degradation.
  - Data in runs_e2e_cl/ runs_e2e_cx/ (meta+agent.log; traces left on VM).
    VM stopped.
- IMPLICATION: #3 reframes the paper from "all 4 limits broadly harm agents"
  to the more defensible "mechanisms are real; a lightweight coding task
  triggers only CPU (+ memory below the agent's footprint); memory/disk bite
  when the workload stresses them." To weave into Mahsa 1-10 next.
- IMPLEMENTED all of Mahsa 1-10 in paper2.tex (user's working copy), with
  the mechanism-study + realistic-task-reality-check framing:
  #1 total vs tool-phase time separated (Prob 2 total ~8->11s vs phase;
     4.7x/295x/3.4x labelled tool-phase); #2 dropped "OS-bound/dominates" ->
     "limits increase execution time; model still ~half at 0.25 core";
  #3 NEW section "A Realistic Task: Which Limit Bites?" (+ tab:e2e): only CPU
     slows the coding task, memory kills it below ~190MiB footprint, disk
     never; Codex survives tighter; #4 two behavior regimes (tool-OOM=agent
     survives+reports; agent-OOM=thrash+die no report); #5 counter-vs-trace
     worked example (memory.events 8505 high + 1.05M refaults vs trace shows
     the file-read tool blocking); #6 "observed little contention", dropped
     causal "proves"; #7 fixed the false <1% claim (deterministic metrics
     few %, wall +-15% from LLM) + spread in text; #8 thresholds as RANGES
     (OOM 640-768MB, slowdown 1152-1536MB, agent OOM 128-192MiB, "bounded"
     not "located"); #9 >=10ms stalls "present even at W<=C, jumps to 138";
     #10 reconciled io bytes/time/bandwidth (io.stat 1.23GB const; device
     col 205/205/122/60; fixed faster-storage sentence).
  Structure verified: 22/22 envs, 9 tables, 1 figure, 10 sections, all refs
  resolve. NOTE: paper now longer than 4pp (added section+table) - trimming
  to Naser's 4pp is a separate later pass. Data in runs_e2e_cl/cx (meta only).