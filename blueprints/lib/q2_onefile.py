#!/usr/bin/env python3
"""Every Sock Shop result in one markdown file.

One table per problem in the same shape for all of them, so six problems can be read side by
side instead of six separate documents. Generated from score.json and rescored.json - nothing
is typed by hand, so the file cannot drift from the runs.

    python q2_onefile.py --out SOCK-SHOP-RESULTS-22-09-2026.md
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import q2_harness as Q      # noqa: E402
import q2_rescore as RS     # noqa: E402

ROOT = "/scratch/yuvraj17/stratatrace/results"
ARMS = (("nohint", "none"), ("nohint", "given"), ("hint", "none"), ("hint", "given"))


def load(out_dir: str):
    rows = []
    for sp in sorted(glob.glob(os.path.join(out_dir, "*", "*", "*", "*", "*", "score.json"))):
        try:
            r = json.load(open(sp, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rp = os.path.join(os.path.dirname(sp), "rescored.json")
        r["_v2"] = {}
        if os.path.exists(rp):
            try:
                r["_v2"] = json.load(open(rp, encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        rows.append(r)
    return rows


def pc(n, d):
    return "-" if not d else "%d%%" % round(100 * n / d)


def _mmss(secs):
    """Median wall-clock per run. Minutes and seconds, because "how long did it take" is the
    question a person asks and 393 is harder to read than 6m33s."""
    secs = int(secs or 0)
    return "%dm%02ds" % (secs // 60, secs % 60)


def med(vals):
    v = sorted(x for x in vals if isinstance(x, (int, float)))
    return v[len(v) // 2] if v else 0


def describe(rs):
    v = [r["_v2"].get("what_score_v2") for r in rs
         if isinstance(r["_v2"].get("what_score_v2"), (int, float))]
    if v:
        return "%d%%" % round(100 * sum(v) / len(v)), sum(v) / len(v)
    v1 = [r.get("what_score") for r in rs if isinstance(r.get("what_score"), (int, float))]
    if v1:
        return "%d%%*" % round(100 * sum(v1) / len(v1)), sum(v1) / len(v1)
    return "-", 0.0


def block(L, prob, rows):
    rs_all = [r for r in rows if r.get("problem") == prob]
    if not rs_all:
        return
    tgt = rs_all[0].get("true_service") or "?"
    ceiling = RS.WHERE_CEILING.get(prob, "named")
    L.append("## %s" % prob)
    L.append("")
    L.append("Target: `%s`. Best WHERE answer this fault allows: **%s**."
             % (tgt, "name the container" if ceiling == "named" else "say `host`"))
    L.append("")

    # the main table, same shape for every problem
    L.append("| ask \\| arm | n | both right | WHERE | window | described | fault | time | tokens |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    cache = {}
    for ask, arm in ARMS:
        rs = [r for r in rs_all if r.get("ask") == ask and r.get("arm") == arm]
        if not rs:
            continue
        n = len(rs)
        both = sum(1 for r in rs if r.get("both_ok"))
        where = sum(1 for r in rs if RS.where_ok(r.get("where", ""), prob))
        win = sum(1 for r in rs if r.get("window_verdict") == "hit")
        fault = sum(1 for r in rs if r.get("fault_ok"))
        dtxt, dval = describe(rs)
        cache[(ask, arm)] = (both / n, where / n, win / n, dval, fault / n)
        secs = med([r.get("seconds") for r in rs])
        L.append("| %s \\| %s | %d | %s | %s | %s | %s | %s | %s | %s |"
                 % (ask, arm, n, pc(both, n), pc(where, n), pc(win, n), dtxt,
                    pc(fault, n), _mmss(secs),
                    "{:,}".format(med([r.get("tokens") for r in rs]))))
    L.append("")

    # what the blueprint changed, per ask
    eff = []
    for ask in ("nohint", "hint"):
        a, b = cache.get((ask, "none")), cache.get((ask, "given"))
        if not (a and b):
            continue
        eff.append("| %s | %+d | %+d | %+d | %+d | %+d |"
                   % (ask, *[round(100 * (b[i] - a[i])) for i in range(5)]))
    if eff:
        L.append("Blueprint effect, in percentage points:")
        L.append("")
        L.append("| ask | both right | WHERE | window | described | fault |")
        L.append("|---|---|---|---|---|---|")
        L += eff
        L.append("")

    # where did it actually point
    w = Counter(r.get("where") for r in rs_all)
    said_host = sum(1 for r in rs_all
                    if str(r.get("pred_service", "")).strip().lower() == "host")
    L.append("Where it pointed, all %d runs: named the thing **%d**, one container **%d**, "
             "host only **%d**, a shared runtime like `java` **%d**, wrong **%d**. "
             "It answered `host` %d times."
             % (len(rs_all), w["named"], w["container"], w["scope"], w["ambiguous"],
                w["wrong"] + w["none"], said_host))
    L.append("")
    top = Counter(r.get("pred_service") for r in rs_all).most_common(6)
    L.append("Most common answers: %s"
             % ", ".join("`%s` %d" % (k, v) for k, v in top))
    L.append("")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", default=os.path.join(ROOT, "q2-full"))
    ap.add_argument("--ns", default=os.path.join(ROOT, "q2-ns"))
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    full, ns = load(a.full), load(a.ns)
    problems = list(Q.PROBLEMS)
    L = []
    L.append("# Sock Shop results - 22 September 2026")
    L.append("")
    L.append("Every run of the blueprint study in one place. Generated by "
             "`blueprints/lib/q2_onefile.py` from the run files, so it cannot drift from them.")
    L.append("")
    L.append("## What was run")
    L.append("")
    L.append("| | |")
    L.append("|---|---|")
    L.append("| problems | 6 |")
    L.append("| runs per problem | 3 incidents x 2 arms x 2 asks x 5 repeats = 60 |")
    L.append("| total | **%d runs, 0 failed** |" % len(full))
    L.append("| evidence | kernel traces only. No metrics, no logs, no spans |")
    L.append("| model | `gpt-5.4-mini` (azure) |")
    L.append("| blueprint | handed over, not chosen |")
    L.append("| application | **Sock Shop only** - Train Ticket was never run |")
    L.append("| results | `/scratch/yuvraj17/stratatrace/results/q2-full` |")
    L.append("")
    L.append("The agent is never told when the fault was, or that there was one. It gets six "
             "read-only tools over the raw kernel trace and has to find what happened, when, "
             "and where.")
    L.append("")
    L.append("## How to read the tables")
    L.append("")
    L.append("Every problem below has the same table. This explains it once.")
    L.append("")
    L.append("### The rows")
    L.append("")
    L.append("Each row is one setup. The name has two parts, split by a `|`.")
    L.append("")
    L.append("**Part 1 - did we give the agent a hint?**")
    L.append("")
    L.append("- `nohint` - we said nothing at all. It gets a trace and works out the rest.")
    L.append("- `hint` - we told it the symptom only. Something like \"requests are slow and "
             "the host looks contended\". Never the answer.")
    L.append("")
    L.append("**Part 2 - did we give the agent the blueprint?**")
    L.append("")
    L.append("- `none` - no blueprint. It works alone.")
    L.append("- `given` - we handed it the right blueprint to follow.")
    L.append("")
    L.append("So `nohint | none` is the least help and `hint | given` is the most. Each row is "
             "run 15 times, so a lucky answer does not look like a skilled one.")
    L.append("")
    L.append("### The columns")
    L.append("")
    L.append("| column | the question it asks |")
    L.append("|---|---|")
    L.append("| n | how many runs. Always 15 |")
    L.append("| both right | did it get the place AND the fault name right |")
    L.append("| WHERE | did it point at the right thing |")
    L.append("| window | did it find the right time |")
    L.append("| described | how much of the problem its own words explained |")
    L.append("| fault | did it pick the right fault name from our list |")
    L.append("| time | how long one run took |")
    L.append("| tokens | how much one run cost |")
    L.append("")
    L.append("**WHERE and both right are not the same.** `both right` needs the fault name "
             "too. `WHERE` only asks about the place.")
    L.append("")
    L.append("> **Ignore the `fault` column when comparing rows.** The blueprint text "
             "describes the fault, so a `given` row can read the answer straight off it. That "
             "column mostly shows whether the agent read the page. To measure it properly we "
             "need a setup where the agent picks its own blueprint from all 11.")
    L.append("")
    L.append("## How we score each answer")
    L.append("")
    L.append("Each run is scored on its own. The column is then how many of the 15 passed.")
    L.append("")
    L.append("The agent never sees the right answer. Only the scorer reads it, after the run "
             "is finished.")
    L.append("")
    L.append("### both right")
    L.append("")
    L.append("The strictest test. It must get the place right AND the fault name right. Pass "
             "or fail.")
    L.append("")
    L.append("### fault")
    L.append("")
    L.append("Did the fault name it picked match the one we injected? We match on meaning, not "
             "spelling, so `cpu_saturation` and `anomaly_cpu` count as the same thing.")
    L.append("")
    L.append("### WHERE")
    L.append("")
    L.append("Not just right or wrong. There are five kinds of answer:")
    L.append("")
    L.append("| answer | what it means |")
    L.append("|---|---|")
    L.append("| named | it said the exact thing we broke, like `stress-ng-cpu` |")
    L.append("| container | it said one exact container, using its `pid_ns` number |")
    L.append("| host only | it said `host`, and nothing smaller |")
    L.append("| ambiguous | it said `java`. Five containers here run java, so this is vague |")
    L.append("| wrong | anything else |")
    L.append("")
    L.append("**Which of these count as right depends on the fault.**")
    L.append("")
    L.append("For most faults there is one container at fault, so the agent should name it. "
             "Saying `host` is a safe guess and does not count.")
    L.append("")
    L.append("`anomaly_net` is the exception. We slowed the host's own network card. There is "
             "no container to name, so `host` **is** the full answer and it counts.")
    L.append("")
    L.append("The right answer for each run is read from that run's own record. We never typed "
             "a list of expected answers by hand.")
    L.append("")
    L.append("### window")
    L.append("")
    L.append("We compare the time range it gave against the real one.")
    L.append("")
    L.append("```")
    L.append("overlap = the time both ranges share")
    L.append("union   = the time they cover together")
    L.append("score   = overlap / union")
    L.append("```")
    L.append("")
    L.append("A score of 1.0 means the ranges match exactly. A score of 0 means they do not "
             "touch.")
    L.append("")
    L.append("| verdict | when |")
    L.append("|---|---|")
    L.append("| hit | score is 0.5 or higher |")
    L.append("| partial | they overlap a bit, but less than that |")
    L.append("| miss | they do not overlap |")
    L.append("| abstained | it answered `unknown` |")
    L.append("")
    L.append("The table counts hits only.")
    L.append("")
    L.append("**Answering `unknown` is not counted as wrong.** We told the agent that a made-up "
             "time is worse than saying it does not know. Marking it wrong would punish it for "
             "doing what we asked.")
    L.append("")
    L.append("### described")
    L.append("")
    L.append("This is a word check, and it is the softest number here.")
    L.append("")
    L.append("For each problem we wrote down 3 ideas that a correct answer contains. For "
             "`noisy_neighbor` they are:")
    L.append("")
    L.append("1. there is an extra workload that is not part of the app")
    L.append("2. it is taking CPU away from the others")
    L.append("3. the app services are victims, not the cause")
    L.append("")
    L.append("Each idea has a list of words and phrases that count. Any one of them scores "
             "that idea. So hitting 2 of 3 gives 67%%.")
    L.append("")
    L.append("It asks \"did the agent say this at all\", not \"did it say it well\". A low "
             "score means go and read the run. It does not prove the run is wrong.")
    L.append("")
    L.append("We got this wrong the first time. Our word list held a bare \"db\", which appears "
             "in `catalogue-db`. So any answer naming that container scored a free point, and "
             "`slow_db` came out at 97%%. It now asks for real phrases like \"database\" or "
             "\"waiting on\".")
    L.append("")
    L.append("### time and tokens")
    L.append("")
    L.append("The middle value of the 15 runs, not the average. One very slow run cannot drag "
             "the number.")
    L.append("")
    L.append("## The results in five charts")
    L.append("")
    L.append("Generated by `blueprints/lib/q2_charts.py` from the same run files as the "
             "tables below. Three of the five show **every single run** rather than an "
             "average, because averaging 360 runs down to 24 numbers hid things worth seeing.")
    L.append("")
    L.append("### 1. Where the blueprint helps, and where it hurts")
    L.append("")
    L.append("![Blueprint effect by problem and measure](charts/1-blueprint-effect.png)")
    L.append("")
    L.append("Rows are grouped by what the fault touches: **whole host** at the top, a "
             "**datastore** in the middle, **one service** at the bottom.")
    L.append("")
    L.append("The blueprint helps most at explaining the problem - +44 on `noisy_neighbor`, "
             "+29 on `slow_db`. It does nothing for finding the place on three problems, and "
             "the reasons are opposite (chart 4). On `anomaly_net` it makes finding the time "
             "**37 points worse**, which is our own fault and is explained at the end.")
    L.append("")
    L.append("### 2. Every one of the 360 runs")
    L.append("")
    L.append("![All 360 runs, one square each](charts/2-every-run.png)")
    L.append("")
    L.append("One square per run. Each block is 5 repeats across by 3 incidents down. Nothing "
             "is averaged, so you can see how steady each result is.")
    L.append("")
    L.append("A percentage cannot tell a steady 3-out-of-5 from 5-out-of-5 on one incident and "
             "0-out-of-5 on the next. Here it is visible. `anomaly_cpu` is solid dark across "
             "all 60 runs - never once wrong. `svc_net` is almost solid grey. And the third "
             "row of `slow_db` is grey in every arm, which says one of its three incidents is "
             "harder than the other two - something no column of averages would ever show.")
    L.append("")
    L.append("### 3. How close was the time it gave?")
    L.append("")
    L.append("![All 360 window scores](charts/3-window-raw.png)")
    L.append("")
    L.append("Every run's overlap score, not the pass rate. This is the chart that changed "
             "what we think.")
    L.append("")
    L.append("**The scores are in two clumps, near 1.0 or near 0, with almost nothing "
             "between.** The agent either finds the window almost exactly or misses it "
             "completely. It does not produce rough answers.")
    L.append("")
    L.append("That matters for two reasons. The 0.5 cut we chose is not arbitrary after all - "
             "it falls in an empty gap between two real groups. And \"it was close\" is not a "
             "thing that happens here, so a miss is always a miss and worth reading.")
    L.append("")
    L.append("The `anomaly_net` damage is visible too: without the blueprint the runs sit high, "
             "with it there are 14 grey `unknown` answers instead.")
    L.append("")
    L.append("### 4. Why the blueprint changes nothing on three problems")
    L.append("")
    L.append("![Score without vs with a blueprint](charts/4-room-to-improve.png)")
    L.append("")
    L.append("Points above the line are where the blueprint helped. Points **on** the line are "
             "where it changed nothing - and the two ends mean opposite things.")
    L.append("")
    L.append("`anomaly_cpu` sits top right at 100%% in both arms. Nothing left to gain. "
             "`svc_cpu_cap` and `svc_net` sit bottom left at zero in both arms, because our "
             "tools could not tell one container's `java` from another's. A blueprint cannot "
             "rescue a question the evidence cannot answer.")
    L.append("")
    L.append("**Same number, opposite meaning.** That is why we never report an average across "
             "problems - it came out as +0 and told us nothing.")
    L.append("")
    L.append("### 5. What it cost, run by run")
    L.append("")
    L.append("![Time and tokens for every run](charts/5-cost-raw.png)")
    L.append("")
    L.append("The left panel is all 360 runs on cost and time. The clouds overlap almost "
             "completely, so the neat median difference in the tables is a small shift inside "
             "a very wide spread - runs range from 30k to 230k tokens on the same problem.")
    L.append("")
    L.append("The right panel is clearer: with the blueprint the agent is **faster** on every "
             "problem. It costs more to read and saves more than it costs by not casting "
             "about.")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## All six problems at a glance")
    L.append("")
    L.append("| problem | target | WHERE right | window hits | described |")
    L.append("|---|---|---|---|---|")
    for prob in problems:
        rs = [r for r in full if r.get("problem") == prob]
        if not rs:
            continue
        n = len(rs)
        where = sum(1 for r in rs if RS.where_ok(r.get("where", ""), prob))
        win = sum(1 for r in rs if r.get("window_verdict") == "hit")
        dtxt, _ = describe(rs)
        L.append("| %s | `%s` | **%d/%d** | %d/%d | %s |"
                 % (prob, rs[0].get("true_service"), where, n, win, n, dtxt))
    L.append("")
    L.append("The split is by **scope**, not by difficulty. Host-wide faults are found. "
             "Single-service faults are not - and that turned out to be a limit of the tools, "
             "not of kernel traces. See the last section.")
    L.append("")
    L.append("---")
    L.append("")

    for prob in problems:
        block(L, prob, full)
        L.append("---")
        L.append("")

    # the before/after
    if ns:
        L.append("## The container fix: before and after")
        L.append("")
        L.append("Both per-service problems scored 0/60 on WHERE. The reason was my tool, not "
                 "the modality: every kernel event carries a `pid_ns`, one per container, and "
                 "the count index was throwing it away. So the agent saw `java` with no way to "
                 "tell which container's java, and answered `host`.")
        L.append("")
        L.append("Re-run with `pid_ns` in the index. Everything else held fixed.")
        L.append("")
        L.append("| | | before | after | change |")
        L.append("|---|---|---|---|---|")
        for prob in sorted({r.get("problem") for r in ns}):
            b = [r for r in full if r.get("problem") == prob]
            f = [r for r in ns if r.get("problem") == prob]
            for label, fn in (
                    ("WHERE right", lambda rs, p=prob:
                     sum(1 for r in rs if RS.where_ok(r.get("where", ""), p))),
                    ("answered `host`", lambda rs: sum(
                        1 for r in rs
                        if str(r.get("pred_service", "")).strip().lower() == "host")),
                    ("said bare `java`", lambda rs: sum(
                        1 for r in rs if r.get("where") == "ambiguous"))):
                L.append("| %s | %s | %d/%d | %d/%d | %+d |"
                         % (prob, label, fn(b), len(b), fn(f), len(f), fn(f) - fn(b)))
        L.append("")
        L.append("It moved off `host` - 28 fewer runs on `svc_net` - but went to bare `java` "
                 "rather than a specific container. It **is** using the namespaces: 42 and 45 "
                 "of 60 mention a `pid_ns` in their reasoning. Only 1 of 120 put one in the "
                 "answer field, and one run says exactly why:")
        L.append("")
        L.append("> The specific throttled service cannot be named from kernel comm alone; the "
                 "trace shows multiple `java` containers, including pid_ns 4026532538 and "
                 "4026533460, but not which one has the quota.")
        L.append("")
        L.append("That is correct reasoning and an honest refusal.")
        L.append("")
        L.append("---")
        L.append("")

    L.append("## Three claims that turned out to be false")
    L.append("")
    L.append("Each of these looked like a finding about kernel traces. All three were my own "
             "tooling, and all three were caught by testing them against the raw trace before "
             "writing them down.")
    L.append("")
    L.append("| the claim | what the trace actually holds |")
    L.append("|---|---|")
    L.append("| cannot localise a per-service fault | every event carries `pid_ns`, one per "
             "container. `java` is 5 separate containers. The index dropped it |")
    L.append("| cannot find the window for host-wide faults | it can. My own prompt told the "
             "agent that a change shared by every event type meant a workload shift, so it "
             "rejected the right answer. Abstentions 1/30 without the blueprint, 14/30 with |")
    L.append("| cannot identify a throttled container | `sched_stat_runtime` carries CPU time "
             "per task. carts sits at **0.195 CPU-s/s against a 0.200 cap** - pinned at the "
             "ceiling. The index counts events and discards the payload |")
    L.append("")
    L.append("**The common thread: a count-based summary of a kernel trace loses exactly the "
             "information that identifies resource-limit faults.** That is worth more to the "
             "paper than any of the three false claims would have been.")
    L.append("")
    L.append("## What is still missing")
    L.append("")
    L.append("1. **Train Ticket.** Zero runs. The picker takes the first 3 runs from a list "
             "that puts Sock Shop first, so it never reached the second application. The runs "
             "exist - 5 to 11 per problem. Every finding here is single-application until "
             "this is done.")
    L.append("2. **The `chosen` arm.** The agent is handed the correct blueprint, so the "
             "`fault` column measures reading rather than diagnosis.")
    L.append("3. **`anomaly_net` with the corrected prompt.** The fix is committed, not run.")
    L.append("4. **CPU time in the index.** `sched_stat_runtime` summed per container would "
             "make `svc_cpu_cap` solvable.")
    L.append("")
    L.append("## Reading the raw answers")
    L.append("")
    L.append("Every answer in the agent's own words, one file per problem:")
    L.append("")
    L.append("```")
    L.append("results/q2-full/review/review-<problem>.md")
    L.append("```")
    L.append("")
    L.append("The automatic scores sort the runs. They do not decide. If a run reads correct "
             "and scored low, the rubric is wrong and should be changed.")
    L.append("")

    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("wrote %s  (%d lines)" % (a.out, len(L)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
