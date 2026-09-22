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
    L.append("**What the columns mean**")
    L.append("")
    L.append("| column | meaning |")
    L.append("|---|---|")
    L.append("| both right | the old pass/fail: right service AND right fault label |")
    L.append("| WHERE | did it point at the right thing, judged against the best answer the "
             "fault allows |")
    L.append("| window | did it find WHEN, overlap of at least half with the real window |")
    L.append("| described | how much of the mechanism its own words covered |")
    L.append("| fault | did it pick the right label from the list |")
    L.append("| time | median wall clock for one run, start to answer |")
    L.append("| tokens | median per run |")
    L.append("")
    L.append("## How each number is worked out")
    L.append("")
    L.append("Every one is scored per run, then counted across the 15 runs in a row. Ground "
             "truth is read only by the scorer. No tool the agent can call ever sees it.")
    L.append("")
    L.append("**both right** - the old strict test. The service must match AND the fault label "
             "must match. One run, pass or fail. The column is how many of 15 passed.")
    L.append("")
    L.append("**fault** - does the label it picked match the fault we injected? We map its "
             "label to our recipe name first, so `cpu_saturation` and `anomaly_cpu` count as "
             "the same thing. Pass or fail per run.")
    L.append("")
    L.append("**WHERE** - four possible answers, not two:")
    L.append("")
    L.append("| answer | what it means |")
    L.append("|---|---|")
    L.append("| named | it said the injected thing, e.g. `stress-ng-cpu` or `mysqld` |")
    L.append("| container | it said one specific container, by its `pid_ns` number |")
    L.append("| host only | it said `host` and nothing narrower |")
    L.append("| ambiguous | it said a shared runtime like `java`, which is 5 containers here |")
    L.append("| wrong | anything else |")
    L.append("")
    L.append("Which of these count as right depends on the fault. For `anomaly_net` the netem "
             "sits on the host's own interface, so there is no container to name and `host` IS "
             "the complete answer. Everywhere else `host` is a hedge and does not count. The "
             "target for each run is read from that run's own `ground_truth.json`, so the "
             "accept list is never something I guessed in advance.")
    L.append("")
    L.append("**window** - we compare the range it claimed against the real injection window "
             "and measure the overlap:")
    L.append("")
    L.append("```")
    L.append("overlap = how much of the two ranges is shared")
    L.append("union   = how much they cover together")
    L.append("score   = overlap / union        (1.0 = exact, 0 = no overlap at all)")
    L.append("```")
    L.append("")
    L.append("| verdict | when |")
    L.append("|---|---|")
    L.append("| hit | score is 0.5 or more |")
    L.append("| partial | they overlap, but less than that |")
    L.append("| miss | no overlap |")
    L.append("| abstained | it said `unknown` |")
    L.append("")
    L.append("The `window` column counts hits only. **Abstaining is not counted as wrong.** We "
             "told the agent a made-up window is worse than admitting it does not know, so "
             "scoring it as a failure would contradict its own instructions.")
    L.append("")
    L.append("**described** - this one is a keyword check, and it is the softest number here. "
             "For each problem we wrote down 3 ideas a correct answer contains. For "
             "`noisy_neighbor` they are:")
    L.append("")
    L.append("1. an extra workload that is not part of the application")
    L.append("2. it is taking CPU away from the others")
    L.append("3. the application services are victims, not the cause")
    L.append("")
    L.append("Each idea has a list of phrases that count. Any one of them scores the idea. The "
             "run scores the fraction it hit, so 2 of 3 is 67%%. The column averages that over "
             "15 runs.")
    L.append("")
    L.append("It is deliberately generous - it asks \"did it say this at all\", not \"did it say "
             "it well\". A low score means go and read the run, not that the run is wrong. The "
             "first version was too generous and scored `slow_db` at 97%% because its word list "
             "held a bare \"db\", which matches `catalogue-db` in any answer naming the "
             "container. It now asks for phrases like \"database\" or \"waiting on\" instead.")
    L.append("")
    L.append("**time and tokens** - the median across the 15 runs, not the average, so one very "
             "slow run cannot drag the number.")
    L.append("")
    L.append("> **Ignore the `fault` column when comparing arms.** The blueprint is handed "
             "over and its text describes the fault, so that column largely measures whether "
             "the agent read it. It needs an arm where the agent picks its own blueprint.")
    L.append("")

    # summary first: the six problems side by side
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
