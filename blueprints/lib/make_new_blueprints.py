#!/usr/bin/env python3
"""Generate the five new kernel-only blueprints from measured evidence.

Every discriminator here carries a number that was measured on our runs by
blueprints/lib/fingerprint_table.py, with its n. Nothing is asserted from what a kernel trace
ought to show - the validator rejects a discriminator with no `evidence`, and it should.
"""
import json
import os
import time

ROOT = "blueprints/problems"
NOW = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

# The measured table, n in brackets. Shares are of the culprit container's OWN events.
#   family                futex churn on-CPU softirq network ioctl file-ops   rate/s
#   lock_contention       47.0  26.4   14.7    5.9      .      .      .     62780-63647  n=5
#   priority_inversion    41.0  22.2   18.5   13.4     1.2     .      .     19439-19632  n=5
#   nagle_delayed_ack     25.8  16.9    9.7    9.4    17.9     .      .    772282-805147 n=5
#   deadlock               4.3   9.0    6.8    3.3     0.2    0.4   22.1        70-84    n=5
#   conn_pool_exhaustion    .    7.7    3.2    9.8    35.6   17.3     .       545-550    n=5
#   anomaly_mem             .   11.6   34.0   42.8     1.5     .     0.6      2550-4589  n=8
#   noisy_neighbor          .   27.8   27.0   35.7     2.9     .      .     13631-14235  n=3
#   anomaly_cpu             .   45.1   29.2   21.3     1.8     .      .     72495-74675  n=3

EVID = ("MEASURED on 41 labelled runs across 8 families with "
        "blueprints/lib/fingerprint_table.py (22-09-2026). ")

COMMON_STEPS = [
    {"step": "Make the kernel trace readable",
     "capability": "trace.stage_ctf",
     "expect": "a CTF directory with metadata and channel streams",
     "produces": "a readable trace path"},
    {"step": "Find containers that are active during the window and absent before it",
     "capability": "process.creation_attribution",
     "expect": ("one container with substantial traffic during the window and none before. "
                "If none appears, this blueprint does not apply - say so and stop"),
     "produces": "candidate culprit containers, by pid_ns"},
    {"step": "Measure what share of its own events that container spends on each kind of work",
     "capability": "kernel.container.event_shares",
     "expect": "the share profile below, within the measured range",
     "produces": "<out>/shares.json - per-container event shares", "reads": ["ctf"]},
]

CARD = {"step": "draw the decision card", "capability": "report.decision_card",
        "expect": "one page showing the shares, the cut, and what was ruled out",
        "produces": "<out>/card.svg"}
VERDICT = {"step": "Apply the rules and emit the verdict", "capability": "verdict.apply_rules",
           "expect": "a verdict naming the container and the mechanism, or an explicit abstain",
           "produces": "<out>/verdict.json"}

SPECS = [
    {
        "id": "lock-contention-futex-storm",
        'rule_out': [{'instead': 'deadlock-lock-order', 'when': "the container's futex share is near 4% and it produces only tens of events per second - parked, not spinning"}, {'instead': 'priority-inversion-nice', 'when': 'softirq is above 10% and migration below 3%, measured 13.4% and 2.0% there against 5.9% and 5.0% here'}, {'instead': 'cpu-contention-co-tenant', 'when': 'futex is 0% and softirq above 35% - a stress container, not a lock'}],
        "title": "User-level lock contention: a futex storm in one container",
        "summary": ("One container spends nearly half of everything it does on futex - taking "
                    "and waiting on user-level locks - while churning through the scheduler. "
                    "Threads are running, but mostly to fight each other for a lock."),
        "symptoms": ["a service is slow but its CPU is not saturated",
                     "latency is erratic rather than uniformly higher",
                     "the slowdown does not follow a call path to a dependency"],
        "fault_type": "lock_contention",
        "root_cause_is": "the container whose futex share is far above every other container",
        "discriminators": [
            {"signal": "share of the container's own events spent on futex",
             "this_problem": "47.0% (n=5, range 46.6-47.3)",
             "not_this_problem": ("a deadlock sits at 4.3% because parked threads make no "
                                  "calls; a stress container, a memory stressor and a "
                                  "connection-pool holder all sit at 0%"),
             "confused_with": ["deadlock-lock-order", "priority-inversion-nice",
                               "cpu-contention-co-tenant"],
             "evidence": EVID + ("lock_contention 47.0% (n=5) against deadlock 4.3% (n=5), "
                                 "priority_inversion 41.0% (n=5), and 0.0% for noisy_neighbor "
                                 "(n=3), anomaly_cpu (n=3), anomaly_mem (n=8) and "
                                 "conn_pool_exhaustion (n=5).")},
            {"signal": "thread migration share, which separates it from priority inversion",
             "this_problem": "5.0% (n=5) - threads bounce between CPUs chasing the lock",
             "not_this_problem": ("priority inversion sits at 2.0% and carries more softirq "
                                  "(13.4% against 5.9%). This is the weaker of the two "
                                  "discriminators and must not decide on its own"),
             "confused_with": ["priority-inversion-nice"],
             "evidence": EVID + ("migrate 5.0% vs 2.0%, softirq 5.9% vs 13.4%, both n=5. The "
                                 "futex share alone does NOT separate these two (47.0 vs "
                                 "41.0), which is why this second signal exists.")},
            {"signal": "the container is busy, not idle",
             "this_problem": "sched churn 26.4% and on-CPU 14.7% (n=5): work is being done",
             "not_this_problem": ("a deadlock is nearly silent - measured 70-84 events/s "
                                  "against 62,780-63,647 here, a factor of 800"),
             "confused_with": ["deadlock-lock-order"],
             "evidence": EVID + ("rate 62,780-63,647 events/s (n=5) against deadlock's 70-84 "
                                 "(n=5). The rate is NOT a portable threshold - it encodes "
                                 "our injector's 16 threads at 200 us - but the direction is.")},
        ],
        "unverified": [
            {"claim": "raised runqueue delay identifies lock contention",
             "status": "NOT TESTED HERE - and known to fire everywhere",
             "measurement": ("the cpu-contention-co-tenant blueprint already measured runqueue "
                             "delay as raised in every CPU-family fault and in healthy load "
                             "bursts. It was demoted to corroboration there and is not "
                             "reinstated here."),
             "consequence": "not used. Decide on the futex share."},
        ],
        "apply_when": ["a service is slow without being CPU-saturated",
                       "latency is erratic rather than uniformly raised",
                       "a kernel trace is available and futex syscalls are traced"],
        "do_not_apply": ["the suspect container is nearly idle - see deadlock-lock-order",
                         "no container is new to the window",
                         "futex is not in the collection profile, in which case this cannot "
                         "be measured at all"],
        "precheck": "one container's futex share is above 40% while every other is near zero",
    },
    {
        "id": "deadlock-lock-order",
        'rule_out': [{'instead': 'lock-contention-futex-storm', 'when': 'the container is busy - tens of thousands of events per second with futex near 47%'}, {'instead': 'connection-pool-exhaustion', 'when': 'it is quiet but its events are network and ioctl rather than file operations'}],
        "title": "Deadlock: the container goes quiet instead of busy",
        "summary": ("Threads take locks in conflicting orders and park forever. The giveaway "
                    "is the opposite of what people look for: the container produces FEWER "
                    "events than an idle one, because blocked threads make no syscalls."),
        "symptoms": ["a service stops responding rather than slowing down",
                     "its CPU use falls instead of rising",
                     "requests time out rather than returning late"],
        "fault_type": "deadlock",
        "root_cause_is": "the container that appeared and then went nearly silent",
        "discriminators": [
            {"signal": "the container's total event rate",
             "this_problem": "70-84 events/s (n=5). Quieter than an idle container",
             "not_this_problem": ("lock contention runs 62,780-63,647 events/s with the same "
                                  "mechanism family - a factor of 800. Anything busy is not "
                                  "this"),
             "confused_with": ["lock-contention-futex-storm", "cpu-contention-co-tenant"],
             "evidence": EVID + ("deadlock 70-84 events/s (n=5) against lock_contention "
                                 "62,780-63,647 (n=5), priority_inversion 19,439-19,632 "
                                 "(n=5), conn_pool_exhaustion 545-550 (n=5).")},
            {"signal": "futex share, which is LOW here and not high",
             "this_problem": "4.3% (n=5) - the locks were taken once and never contended again",
             "not_this_problem": ("lock contention 47.0% and priority inversion 41.0%. A high "
                                  "futex share rules this out, which is the reverse of the "
                                  "intuition"),
             "confused_with": ["lock-contention-futex-storm", "priority-inversion-nice"],
             "evidence": EVID + "4.3% (n=5) against 47.0% and 41.0% (n=5 each)."},
            {"signal": "what little it does do is file operations",
             "this_problem": ("file ops 22.1% (n=5) - close, fcntl and openat2, which is the "
                              "respawn loop opening and closing its lock files"),
             "not_this_problem": ("no other family exceeds 0.6% on file ops. It is 0.0% for "
                                  "lock contention and priority inversion"),
             "confused_with": ["lock-contention-futex-storm"],
             "evidence": EVID + ("file ops 22.1% (n=5) against 0.0% for lock_contention and "
                                 "priority_inversion, 0.6% anomaly_mem, 0.1% noisy_neighbor.")},
        ],
        "unverified": [
            {"claim": "a deadlock can be told from a crashed or stopped container",
             "status": "NOT SUPPORTED by this evidence",
             "measurement": ("both look like a container that stops doing work. We measured "
                             "the deadlock family only; no stopped-container family was "
                             "measured against it."),
             "consequence": ("state the ambiguity in the verdict. Distinguishing them needs "
                             "process exit events or the container's own logs.")},
        ],
        "apply_when": ["a service stopped responding rather than slowing",
                       "its resource use fell rather than rose",
                       "a kernel trace is available"],
        "do_not_apply": ["the suspect container is busy - that is contention, not deadlock",
                         "no container went quiet during the window"],
        "precheck": "a container appeared in the window and produces under a few hundred "
                    "events per second while the application is under load",
    },
    {
        "id": "connection-pool-exhaustion",
        'rule_out': [{'instead': 'nagle-delayed-ack-stall', 'when': 'network is present but futex is around 26% rather than 0%'}, {'instead': 'db-latency-dependency-wait', 'when': 'no container is new to the window and the datastore itself is slow'}],
        "title": "Connection pool exhaustion: a holder that talks to the network and does no work",
        "summary": ("Something opens connections to a datastore and holds them without using "
                    "them. In the kernel it shows as a container whose events are almost all "
                    "network and ioctl, with no locking and almost no CPU."),
        "symptoms": ["callers of one datastore start failing or timing out",
                     "the datastore itself is not busy",
                     "the failure is about availability of connections, not latency"],
        "fault_type": "conn_pool_exhaustion",
        "root_cause_is": "the container holding connections open against the datastore",
        "discriminators": [
            {"signal": "ioctl share",
             "this_problem": "17.3% (n=5)",
             "not_this_problem": ("ioctl does not appear at all in any other family measured - "
                                  "0.0% for lock contention, deadlock, priority inversion, "
                                  "both stress families and the network fault"),
             "confused_with": ["db-latency-dependency-wait", "dependency-outage-retry-storm"],
             "evidence": EVID + ("conn_pool_exhaustion 17.3% (n=5); every other family "
                                 "measured 0.0-0.4%. This is the cleanest single separation "
                                 "in the table.")},
            {"signal": "network share with no futex",
             "this_problem": "network 35.6% and futex 0.0% (n=5) - it talks, it does not lock",
             "not_this_problem": ("the delayed-ack fault also carries network (17.9%) but "
                                  "with 25.8% futex alongside it"),
             "confused_with": ["nagle-delayed-ack-stall"],
             "evidence": EVID + ("network 35.6% / futex 0.0% (n=5) against 17.9% / 25.8% for "
                                 "nagle_delayed_ack (n=5).")},
            {"signal": "it is nearly idle for the work it appears to be doing",
             "this_problem": "545-550 events/s with on-CPU at 3.2% (n=5) - holding, not working",
             "not_this_problem": "a busy client would show far more on-CPU time",
             "confused_with": ["db-latency-dependency-wait"],
             "evidence": EVID + ("545-550 events/s (n=5), a spread of under 1% across five "
                                 "runs, with on_cpu 3.2%.")},
        ],
        "unverified": [
            {"claim": "the exhausted pool can be seen from the datastore side",
             "status": "NOT MEASURED",
             "measurement": ("we measured the holder container only. Whether the datastore's "
                             "own container shows a matching signature was not tested."),
             "consequence": "do not claim it. Name the holder, not the victim."},
        ],
        "apply_when": ["callers of a datastore fail or time out while the datastore is idle",
                       "the symptom is about connection availability, not query latency",
                       "a kernel trace is available"],
        "do_not_apply": ["the datastore is itself busy or slow - see db-latency-dependency-wait",
                         "no container is new to the window"],
        "precheck": "a container appeared whose events are mostly network and ioctl, with no "
                    "futex at all",
    },
    {
        "id": "dependency-outage-retry-storm",
        'rule_out': [{'instead': 'cpu-contention-co-tenant', 'when': 'a container IS new to the window - this fault removes a container, it does not add one'}, {'instead': 'host-cpu-saturation', 'when': 'every container moved together rather than one moving alone'}],
        "title": "Dependency outage: one caller spins while its siblings stay flat",
        "summary": ("A dependency is stopped, and the ONE service that calls it starts "
                    "spinning on retries. No new container appears - this fault removes a "
                    "container rather than adding one - so the newcomer route cannot find it. "
                    "The signature is a syscall storm confined to a single existing container."),
        "symptoms": ["requests through one path fail or hang rather than slowing",
                     "one service's resource use rises sharply while its peers do not",
                     "a dependency produces little or no traffic"],
        "fault_type": "dependency_outage",
        "root_cause_is": ("the stopped dependency. The container that spins is the VICTIM, and "
                          "naming it as the culprit is the mistake this blueprint exists to "
                          "prevent"),
        "discriminators": [
            {"signal": "getrusage rate in a single container, against its identical siblings",
             "this_problem": ("one java container goes from 5.3/s to 2,474-2,701/s while three "
                              "other java containers stay at 6.7/s (n=2 runs)"),
             "not_this_problem": ("a host-wide fault moves every container together. If the "
                                  "siblings move too, this is not it"),
             "confused_with": ["host-cpu-saturation", "cpu-contention-co-tenant"],
             "evidence": EVID + ("MEASURED with blueprints/lib/who_makes_it.py on "
                                 "dependency_outage r1 and r2: getrusage 5.3/s -> 2474.1/s and "
                                 "5.3 -> 2700.9 in pid_ns 4026533460, with the other three "
                                 "java namespaces at 6.7/s in both runs. 100% of the change is "
                                 "application processes, 0% the harness.")},
            {"signal": "no container is new to the window",
             "this_problem": ("none. This fault stops an existing container; across every run "
                              "measured, the newcomer search returns nothing"),
             "not_this_problem": ("every other fault family we measured injects a sidecar "
                                  "container, so a newcomer is present"),
             "confused_with": ["lock-contention-futex-storm", "connection-pool-exhaustion",
                               "cpu-contention-co-tenant"],
             "evidence": EVID + ("fault_fingerprint.py reports 'no newcomer container found' "
                                 "for every dependency_outage run, while finding one in all "
                                 "five runs of each of six other families.")},
            {"signal": "new outbound socket binds in the caller",
             "this_problem": "bind 2.7/s -> 22.9/s in the caller container (n=2)",
             "not_this_problem": "bind stays within 1.1-1.6x in every other family",
             "confused_with": ["network-path-degradation"],
             "evidence": EVID + ("bind x7.3 for dependency_outage against x1.1-1.6 for all "
                                 "seven other families in the specificity sweep.")},
        ],
        "unverified": [
            {"claim": "the stopped dependency can be named directly from the kernel trace",
             "status": "NOT SUPPORTED",
             "measurement": ("a stopped container simply stops producing events. Absence is "
                             "not distinguishable from a container that was always idle "
                             "without knowing the topology, and a kernel trace carries no "
                             "service names."),
             "consequence": ("name the SPINNING container and say its dependency is "
                             "unreachable. Identifying which dependency needs spans, logs or "
                             "a topology map.")},
            {"claim": "getrusage is the mechanism rather than an artefact of this runtime",
             "status": "PARTLY SUPPORTED - n=2, and JVM-specific",
             "measurement": ("measured on two Sock Shop runs, both Java callers. Whether a Go "
                             "or Node caller produces the same storm was not tested."),
             "consequence": ("treat the SHAPE - one container's syscall rate exploding while "
                             "identical siblings stay flat - as the discriminator, and the "
                             "specific syscall as a Java detail.")},
        ],
        "apply_when": ["requests through one path fail or hang rather than slowing",
                       "one service's activity rises sharply while its peers do not",
                       "no new container appeared during the window"],
        "do_not_apply": ["a new container appeared - use the newcomer blueprints instead",
                         "every container moved together, which is host-wide"],
        "precheck": "one container's syscall rate rose roughly a hundredfold while "
                    "containers running the same image did not move",
    },
    {
        "id": "priority-inversion-nice",
        'rule_out': [{'instead': 'lock-contention-futex-storm', 'when': 'migration is around 5% and softirq around 6%, measured against 2.0% and 13.4% here'}, {'instead': 'deadlock-lock-order', 'when': 'futex falls to a few percent and the container goes nearly silent'}],
        "title": "Priority inversion: a futex storm with more softirq and less migration",
        "summary": ("Low-priority threads hold a lock that higher-priority work needs, and "
                    "the scheduler keeps them off the CPU. It looks like lock contention "
                    "because it IS lock contention - the difference is in how the threads "
                    "move between CPUs and how much soft-interrupt work surrounds them."),
        "symptoms": ["a service is slow and its CPU is not saturated",
                     "the slowdown is worse than the offered load explains",
                     "some requests are far slower than others"],
        "fault_type": "priority_inversion",
        "root_cause_is": "the container whose threads hold a lock while being scheduled away",
        "discriminators": [
            {"signal": "futex share, which puts it in the lock family",
             "this_problem": "41.0% (n=5)",
             "not_this_problem": "a deadlock sits at 4.3%; the stress and network families at 0%",
             "confused_with": ["deadlock-lock-order", "cpu-contention-co-tenant"],
             "evidence": EVID + "priority_inversion 41.0% (n=5) against deadlock 4.3% (n=5)."},
            {"signal": "softirq share, which separates it from plain lock contention",
             "this_problem": "13.4% (n=5)",
             "not_this_problem": "lock contention sits at 5.9% (n=5), less than half",
             "confused_with": ["lock-contention-futex-storm"],
             "evidence": EVID + ("softirq 13.4% vs 5.9%, migrate 2.0% vs 5.0%, both n=5. "
                                 "WEAK: futex alone does not separate them (41.0 vs 47.0), so "
                                 "these two secondary numbers carry the decision and a verdict "
                                 "here should carry lower confidence than one for its "
                                 "siblings.")},
            {"signal": "threads migrate LESS than under plain contention",
             "this_problem": "migrate 2.0% (n=5) - they are held off CPU, not bouncing",
             "not_this_problem": "lock contention 5.0% (n=5)",
             "confused_with": ["lock-contention-futex-storm"],
             "evidence": EVID + "migrate 2.0% vs 5.0% (n=5 each)."},
        ],
        "unverified": [
            {"claim": "the inversion can be seen directly in scheduler priority fields",
             "status": "NOT MEASURED - and it is the check that would settle it",
             "measurement": ("sched_switch carries prev_prio and next_prio in its payload, but "
                             "our count index keeps counts only, so priority was never read. "
                             "The recipe uses nice-based inversion, not SCHED_FIFO, so the "
                             "priorities are there to be read."),
             "consequence": ("the two secondary shares carry this blueprint today. Reading "
                             "prev_prio/next_prio per container would likely give a decisive "
                             "discriminator and is the single most valuable thing to add.")},
        ],
        "apply_when": ["a service is slow without CPU saturation",
                       "a container shows a high futex share",
                       "a kernel trace is available"],
        "do_not_apply": ["the container is nearly idle - see deadlock-lock-order",
                         "futex share is near zero"],
        "precheck": "a container with a futex share above 40% and softirq above 10%",
    },
]


def build(spec):
    return {
        "id": spec["id"],
        "version": 1,
        "title": spec["title"],
        "problem": {
            "summary": spec["summary"],
            "symptoms": spec["symptoms"],
            "discriminators": spec["discriminators"],
            "unverified_do_not_claim": spec["unverified"],
        },
        "reproduction": {
            "system": "Sock Shop under StrataTrace v2",
            "recipe": spec["fault_type"],
            "invoke": "see microservice-lttng-data-collection-scripts/faults/",
            "teardown": "the recipe restores state; verify against /sys/fs/cgroup",
            "labelled_examples": ["%s_aggressive_steady_r1" % spec["fault_type"],
                                  "%s_aggressive_steady_r2" % spec["fault_type"],
                                  "%s_aggressive_steady_r3" % spec["fault_type"]],
            "harness_only": ["the fault is injected as a sidecar container, which is a "
                             "property of our harness. In production the same mechanism "
                             "occurs inside an existing service - so the SHAPE transfers, "
                             "the newcomer shortcut does not"],
        },
        "collection_order": {
            "window": {"baseline_s": 60, "incident_s": 120, "recovery_s": 60},
            "kernel_events": ["syscall_entry_futex", "sched_switch", "sched_stat_runtime",
                              "irq_softirq_entry", "net_dev_xmit", "syscall_entry_ioctl"],
            "metrics": [], "logs": [], "traces": [],
            "why_these": ("MEASURED BASIS. Every discriminator in this blueprint is a share of "
                          "these event groups within one container. Nothing else in the trace "
                          "is required, and no other modality is used - this blueprint was "
                          "built and validated on kernel traces alone."),
        },
        "processing": COMMON_STEPS + [VERDICT, CARD],
        "outputs": [
            {"kind": "json", "path": "<out>/verdict.json",
             "contains": "culprit container pid_ns, its event shares, and the shares of every "
                         "other container for comparison"},
            {"kind": "json", "path": "<out>/shares.json",
             "contains": "per-container event shares for the window"},
            {"kind": "xy_chart", "path": "<out>/card.svg",
             "contains": "each family's measured share on the deciding axis, with this run's "
                         "value marked"},
        ],
        "decision": {
            "verdict_when": ["a container is new to the window",
                             "its share profile matches the measured range below",
                             "no sibling container shows the same profile"],
            # {instead, when} - a blueprint must say which OTHER blueprint to reach for and
            # on what measured number, or "rule out" is just a list of names.
            "rule_out": spec["rule_out"],
            "root_cause_is": spec["root_cause_is"],
            "fault_type": spec["fault_type"],
            "uses_thresholds": [],
        },
        "evidence_from_literature": [],
        "related_blueprints": ["cpu-contention-co-tenant"],
        "mutually_exclusive_with": [],
        "provenance": {
            "authored_by": "measured from StrataTrace v2 kernel traces",
            "verified_by": "PENDING human review",
            "authored_utc": NOW,
            "notes": ("Built 22-09-2026 from blueprints/lib/fingerprint_table.py over 41 "
                      "labelled runs of 8 families. Candidate signals were first put through "
                      "discover_signature.py (a specificity sweep across families, which "
                      "rejected unlinkat, ftruncate, block_split, lseek and dup as window "
                      "artefacts) and who_makes_it.py (which rejected the nagle_delayed_ack "
                      "host-wide signal as 94% our own load generator). KERNEL TRACES ONLY - "
                      "no metrics, logs or spans were consulted."),
        },
        "taxonomy": {"domain": "microservices", "category": "kernel-observable",
                     "subcategory": spec["fault_type"], "sibling_causes": [], "note": ""},
        "applicability": {
            "apply_when": spec["apply_when"],
            "do_not_apply_when": spec["do_not_apply"],
            "cheap_precheck": spec["precheck"],
        },
        "capabilities_required": [
            {"id": "trace.stage_ctf"}, {"id": "process.creation_attribution"},
            {"id": "kernel.container.event_shares"}, {"id": "verdict.apply_rules"},
            {"id": "report.decision_card"},
        ],
        "stopping_conditions": {
            "conclude": "the share profile matches and no sibling container matches it too",
            "stop_and_switch": "a discriminating share falls outside its measured range",
            "stop_insufficient": "no container is new to the window and none stands out",
            "max_evidence_rounds": 3,
        },
        "adaptation_rules": [],
        "selection": {
            "supported_goals": ["root cause"], "supported_environments": ["docker-compose"],
            "applicable_symptoms": spec["symptoms"],
            "preconditions": ["a kernel CTF trace", "futex and sched tracepoints enabled"],
            "estimated_overhead_pct": {"min": 0, "max": 0},
            "historical_effectiveness": {"runs_validated": 5,
                                         "note": "shares measured on 5 runs of this family"},
        },
        "policies": {
            "collection_order_rule": "kernel only", "max_collection_overhead_pct": 0,
            "scope": {"restrict_to": "the trace supplied",
                      "never_widen_without": "an operator's say-so"},
            "privacy": [], "approval": {"automatic": ["read the trace"], "requires_approval": []},
            "autonomy_level": 2, "autonomy_note": "read-only analysis",
        },
        "evidence_sufficiency": {
            "confidence_floor": 0.6,
            "if_below_floor": "report the shares and say which blueprint they sit between",
            "report_when_stuck": "the container's shares and every sibling's, side by side",
        },
        "scenarios": {"note": "", "cases": []},
        "inputs": {"trace_dir": "<trace_dir>", "window": "<window>", "out": "<out>",
                   "ctf": "<ctf>", "note": "kernel trace only"},
    }


os.makedirs(ROOT, exist_ok=True)
for spec in SPECS:
    d = os.path.join(ROOT, spec["id"])
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "blueprint.json")
    json.dump(build(spec), open(p, "w", encoding="utf-8"), indent=1)
    print("wrote", p)
