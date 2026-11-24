# Things to fix (blueprints, method, agent harness)

A running list so nothing is forgotten. Started 20-11-2026. When an item is done, move it to
"Done" at the bottom with the date and the commit. Details and reasons are in
`progress-notes/20-11-2026/decisions.md`.

## A. Before we can claim the method in a paper

| # | What | Why it matters |
|---|---|---|
| A1 | Held-out testing: set the bars on part of the runs (or on one application) and report on the rest | Today the bars are set on the same runs that are reported |
| A2 | Agree the pass bars of build Steps 4 and 5 (`METHOD.md`) before the next blueprint is built | They are my proposal; they were never fixed in advance |
| A3 | Repeatability: a second builder follows `METHOD.md` for one family without seeing our tool | Shows the method gives the same rule, not only that we wrote it down |
| A4 | A baseline with no model: run every decisive tool, take the verdicts | A reviewer will ask why a model is needed |
| A5 | Ablation of the parts: no blueprint, tools only, text only, full blueprint | Shows which part gives the gain |
| A6 | Time selection without the label: our sweeps took the slice time from the label. Report results with the time found by the agent (or by a fixed scan) | 4 of 11 first agent runs failed only because of the slice time |
| A7 | `METHOD.md` Step 7 rule (the agent check changes the text only) was not checked against how blueprint 1 was built | It is stated as a rule |

## B. Agent harness (`Blueprint/agent/bp_graph.py`)

| # | What |
|---|---|
| B0 | Scan tool built (24-11, see Done). Still open: (1) tested on 6 runs that had failed, one model, with the tool changed between tries, so this is not an independent test; rerun all families. (2) A scan cuts about 12 slices where 2 were cut before: too heavy on the login node for the lock blueprints (futex slices). (3) The last `code_n_plus_one` run was not repeated after the two harness fixes that followed it (evidence check of scan lines; which verdict line the harness copies) |
| B13 | A scan with a baseline uses the first and the last slice of the trace. Both can be bad: the first is in the load ramp-up (it made two healthy JVMs read CALL AMPLIFICATION in `code_n_plus_one`), and a fault that runs to the end of the trace spoils the last. The agent must judge which baseline to trust; nothing checks that |
| B11 | The "check before rejecting" rule does not fire when the agent leaves through `other`, or when the baseline slice prints the same "nothing" line (then two lines are counted) |
| B12 | Slices with all futex events are heavy: the blueprint 11 runs took 12 and 18 minutes on the login node. Use the 20 s slice of the sweeps, not the README's 60 s |
| B1 | Rerun the seven blueprints that passed on the first try (12, 14, 17, 18, 19, 20, 21) under the final harness; they ran before the "check before rejecting" change |
| B2 | Blueprint 24: both runs were scored by applying the fixed rule to the saved ledger, not by a full rerun |
| B3 | More than one run per blueprint, a second model, and Train Ticket runs. Everything so far is one Sock Shop run, `gpt-6-luna` |
| B4 | Not seen in any run yet: a hand-off between two blueprints, an agent that goes against a verdict line, a "not this fault" run for most blueprints (only 15 and 24 have one) |
| B5 | The agent cuts the same slices again in a later step (allowed, costs time). Tell it which slices already exist in the scratch folder |
| B6 | A tool call with wrong arguments uses up the step budget (seen in blueprints 1 and 24) |
| B7 | Only OpenAI-compatible providers. No Claude message shape yet |
| B8 | `agent_v2.py` and RCA Studio still read `README_v1.md`. Switch them to `blueprint.yaml` / `BLUEPRINT.md`, then retire the old READMEs. RCA Studio's vendored copy goes through its sync script, never by hand |
| B9 | The MCP server prototype (RCA Studio) serves README text. It should serve the steps of `blueprint.yaml` |
| B10 | A selector that picks the first blueprint. Today the blueprint is given |

## C. Single blueprints

| # | Blueprint | What |
|---|---|---|
| C1 | 23 `code_n_plus_one` | Confirmed on 24-11 with the scan tool (right service, 1.5-1.6x against the last slice). The ramp-up trap is real: against the first slice two healthy JVMs also read CALL AMPLIFICATION. Earlier: the agent run failed twice, no rule for a baseline outside the fault at steady load. Also the known thin margin (bar 1.35x, nearest healthy pair 1.28x) and 123 runs not judged |
| C2 | 12 `fd_exhaustion` | README is stale: lists a NOTE the tool no longer prints; status says four runs unchecked but `RESULTS.md` has 10 of 10; cuts 90 s but passes 60 to the tool (the yaml uses 90) |
| C3 | 16, 19, 20 | README gives no rule for choosing the slice time |
| C4 | 19 `data_exfiltration` | `net_loss.py` is run on a slice with fewer event types than its own header asks for. Check that its drop count is right on such a slice |
| C5 | 14 `deadlock` | `futex_wait.py` is run on a slice without the scheduling events its header asks for. README is silent on a contention verdict about another process (yaml: "unconfirmed", same process only) |
| C6 | 21 `dns_delay` | "No lookups seen" (a Go or Java service) is rejected; it should be "cannot be judged". Hand-off to 12 is wider than the README says. Only 3 of 5 labelled runs are clean; musl resolver only |
| C7 | 22 `error_storm` | One command in the yaml (run the tool on the baseline alone) is not in the README. "Refused" names three possible blueprints and no single one |
| C8 | 17 `event_loop_block` | The `serial_work` label comes from the SHAPE line and is not read by code. `code_serial_awaits` label question is still open |
| C9 | 15 `dependency_outage` | The "service gone" outcome was never calibrated on a labelled run. The trace cannot tell `queue_backlog` from `dependency_outage` |
| C11 | 1, 3, 5, 7 | Tools have no `VERDICT:` line and there is no `RESULTS.md`. They need tool work before conversion |
| C12 | 0, 8, 9, 10 | Calibrated on partner traces; the evidence is off git, so build Steps 4 and 5 cannot be shown publicly |
| C13 | 2 `noisy_neighbor` | The "new CPU user, machine not full" verdict is not specific: it fits all 16 `noisy_neighbor` runs and 66 runs of other families |
| C14 | `code_lock_across_io` | No blueprint: no signal at this load. Needs a run at higher load |
| C16 | 11 `priority_inversion` | README is stale against `futex_wait.py`: it lists a verdict the tool never prints (`FUTEX WAITS WITHOUT A SCHEDULING CAUSE`); says one long wait is enough (tool: 2 or more); says the event-wait share is 70% (tool: 50%, and only for a releaser that never waited); says `starved` (tool: `preempted`); leaves out the p99/p50 bar; says cut 60 s (sweeps used 20 s). The tool's own header says 10 ms where its constant is 20 ms. `FAMILIES.md` rows for `lock_contention` ("holders run while holding") and `priority_inversion` (plain rule) do not match `RESULTS.md` (holders sleep; all 10 runs read the chained verdict) |
| C17 | 11 `priority_inversion` | No branch for a plain inversion verdict where the holder was not starved; no meaning given for three `runq_wait.py` verdicts (`MILD`, `MIXED`, `VICTIM NOT SEEN`); `wait_chain.py` prints `NO LONG BLOCKS` and then still a `BLOCKED MOSTLY ON` line. The tools of 11 cannot see periodic connections, so the "check blueprint 18 first" rule rests on the agent's judgment |
| C18 | 6 `conn_pool_exhaustion` | README verdict table has 4 rows, the tool prints 6 verdicts. README says "0 in the baseline", the tool's rule is under 10% of the held count. No `RESULTS.md`. Its "0 false alarms in 292 other runs" and blueprint 22's "286 other runs" come from the same job: check which count is right for each |
| C19 | 2 `noisy_neighbor` | `cpu_hogs.py` has no verdict line, so the `noisy_neighbor` verdict rests on the agent reading a table. No sweep measures whether that step separates `noisy_neighbor` from the 66 other-family runs that also read "machine not full". README says "ten scripts", the table has eleven. The "stop if `sched_switch` is missing" check is a `grep`, not a tool, so it is not in the steps (same in 4 and 11) |
| C20 | 4 `svc_mem_cap` | Request sizes disagree: README says 28.9 or 35.3 GB and 22.5 GB on Train Ticket; `RESULTS.md` says 28.2, 34.5 and 22.0. README tells to use the rate view to find reclaim events, which it cannot show. `mem_pressure.py` has no verdict line for reclaim (the yaml matches plain output lines), takes a `victim_pid` argument it never uses, and counts every event of a process named kswapd. The yaml sends "no reclaim" on to the large-request check; the README does not |
| C21 | 11 `lock_contention` | Agent run inconclusive: the tool read LOCK CONTENTION for the right process, but the agent would not commit because it found no room for a 60 s baseline before the fault (the trace has about 60 s there). Say that a shorter baseline is enough, or that the baseline is optional for this verdict |
| C23 | the triage chain 0 -> 8/9/10/11 | Converted but not run with the agent. These can only run on a local model: their traces are the partner's and must not go to a cloud API. (3 and 5 were run on 23-11) |
| C31 | 3 `slow_db` | Open after the 23-11 fix: (1) the new wording was measured on the fault's own runs only, not checked on other families; (2) naming the dependency is weak: one run named `mongod` where the truth is `mysqld` behind the proxy, and one took `mysqld` as the victim; (3) that run had 3 steps with evidence lines not found in tool output; (4) subtle r2 and r3 were not measured (the 60 ms victim is not in the top-10 table), and `sock_lag.py` shows only 10 rows |
| C24 | 1 `svc_cpu_cap`, 3 `slow_db` | No sweep on all runs and no `RESULTS.md`: no found and no false-alarm counts. 3 rests on one solved case. Every decisive step is a table reading. 1's evaluation file describes an older README and an older `sched_budget.py` |
| C25 | 3 `slow_db` | `sleep_where.py` prints a hint ("piles up in sock_read") that is wrong for a Go or Node victim. `dep_slice.sh` is an old copy of the slice script (no events argument). No rule for "every fd is slow" or "gaps jumped outside the window". Its hand-off to 15 on "no answers" is my reading; the README names no blueprint |
| C26 | 5 `svc_net` | README never uses the family names; the yaml puts `anomaly_net` on the host-wide shape from the run counts (16 and 10). README still speaks of retransmissions in two places where the tool now counts drops only. Confirmation rests on a `sched_budget.py` table |
| C27 | 7 `packet_drop` | Never calibrated (its README says so), no labelled family of this name, so no positive test is possible. README reads drop rates from a table that shows only data volume. `net_drops.py` has two fixed bars (3x, 0.5x) the README denies |
| C28 | 8 `cpu_starvation` | README runs `wait_chain.py` on a slice without the events it needs (the yaml cuts again with the tool's own event list). Unclear whether "starved by higher priority" is this fault (yaml: confirmed). No rule for combining the verdicts of several candidate threads |
| C29 | 9, 10 | 9: a stall verdict with no "it froze" clause is not covered by the README (yaml: unconfirmed). 10: the README contradicts itself on a non-RX concentration (note, different fault, or this fault); the yaml rejects it. 10 needs a second trace as baseline, which the harness cannot pass yet |
| C30 | 0 `host_triage` | The yaml hands off after the first two screens, so a second finding from the starvation screen is not in the triage report. README lists a verdict the tool no longer prints and misses three it does print |
| C32 | 22 `error_storm` | The reset signal comes in bursts, about every 30 s, not all the time: inside the fault 1 of 4 end-to-end 20 s slices shows no reset, and 8 slices with 10 s gaps missed all of them. The sweep's 16 of 16 used one slice at a fixed offset from the injection. State this in the blueprint, and check the other "found N of N" results for the same dependence on where the slice falls |
| C15 | all converted | The rule history is written in the folder for 15 and 24 only; for the rest it is in the decisions files and git |

## D. Data

| # | What |
|---|---|
| D1 | Subtle settings were not collected for `anomaly_cpu`, `error_storm`, `data_exfiltration` |
| D2 | Two runs cannot be sliced: `anomaly_mem_subtle_steady_r3`, `svc_mem_cap_aggressive_steady_r5` |
| D3 | Dataset notes that contradict the measurements and were not edited: `dns_delay` r4, nagle 100 ms against the measured 41 ms |

## E. Housekeeping

| # | What |
|---|---|
| E1 | `next-steps.md` is not updated for this week's work |
| E2 | `progress-notes/16-11-2026/decisions.md` is modified and uncommitted (shared with another session); `agentic-runs-phase2/` is untracked |
| E3 | RCA Studio: `rca.addTrace` shows a raw "Error running command" when the project list fails; the decisions on the MCP prototype and the project feature are not logged; MCP options 2 and 3 were never built |

## Done

| Date | What | Commit |
|---|---|---|
| 20-11-2026 | Method written down (`METHOD.md`); graph harness; blueprints 12 to 24 converted, checked and run once | `84e1c83`, `d108a81`, `ab0041e` |
| 20-11-2026 | Blueprints 2, 4, 6, 11 converted, checked and run once per family (18 of 25 converted) | `b185eaf` |
| 24-11-2026 | Scan tool (`scan_times`) in the harness: one check on slices end to end over the trace, against baselines the agent does not choose. The 6 runs that had failed on the slice time are all confirmed (closes C22) | see git log |
| 23-11-2026 | Blueprint 3: two reading rules measured on 6 `slow_db` runs and changed (connections compared as sets; sleep in locks counts only if it rises); first `RESULTS.md`; agent confirmed 2 of 2 unseen runs | see git log |
| 23-11-2026 | Blueprints 0, 1, 3, 5, 7, 8, 9, 10 converted and checked: all 25 have `blueprint.yaml` and a generated `BLUEPRINT.md`. Closes C10; C11 stays (tools still need a verdict line) | see git log |
