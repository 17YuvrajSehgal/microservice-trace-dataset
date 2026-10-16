#!/usr/bin/env python3
"""Shared plumbing for the kernel-trace agent (agent_v2.py).

Extracted from the retired v1 agent (agentic-rca/agent.py) on 2026-10-16, keeping only what
v2 uses: the kernel-only system prompt, the fault vocabulary, the tool schemas, result
fitting, the retrying API call, the ctf tool dispatch, and diagnosis unmasking. The v1 loop,
the four-modality tools and prompts, the one-shot baseline and the ranked-answer mode were
all study machinery and live on in the main repo's agentic-rca/.

The measurement rationale in the comments is kept on purpose - every cap and every wording
choice here was set from measured campaigns, and the numbers say why.
"""
from __future__ import annotations
import json
import os
import time

import ctf_tool
from ctf_tool import TOOL_DEF as _CTF_TOOL_DEF
from ctf_tool import TIMELINE_DEF as _CTF_TIMELINE_DEF
from ctf_tool import TIMESPAN_DEF as _CTF_TIMESPAN_DEF
from ctf_tool import LINES_DEF as _CTF_LINES_DEF
from ctf_tool import PROCDIFF_DEF as _CTF_PROCDIFF_DEF
from ctf_tool import PROCLIFE_DEF as _CTF_PROCLIFE_DEF
import config

# Tool results sent to the model are capped (the full result always stays in the transcript).
#
# This used to be a flat 6000 chars applied as `full[:SENT_CAP]` - a slice of the JSON STRING.
# Measured over the 720 q2 runs, that was doing real damage:
#
#   - 3,827 of 11,189 tool results were cut, and EVERY cut one was unparseable JSON,
#     chopped mid-number or mid-string.
#   - json.dumps preserves insertion order, so a prefix slice does not sample a result, it
#     DELETES late keys outright. ctf_proclife returns two lists; the second one,
#     `present_throughout`, reached the model in 4.7% of 742 calls.
#   - that matters because of what lands in which list. An injected stress process SPAWNS, so
#     it appears in `present_for_only_part_of_the_recording` (99.3% delivered). A CPU-capped or
#     network-degraded container was already running, so it only appears in `present_throughout`
#     (4.7% delivered). The WHERE scores split exactly along that line.
#
# Budgets below are sized to carry each tool's median result whole; anything larger is trimmed
# by DROPPING WHOLE ROWS, with a note saying so. Each cap is the observed maximum with at
# least 50% headroom; the largest prompt any model call saw was 23k tokens against a 400k
# window, so the headroom is affordable.
SENT_CAP = 30000
SENT_CAP_BY_TOOL = {
    "ctf_proclife": 60000,   # enumerates every container; coverage IS the answer. max 36,709
    "ctf_procdiff": 40000,
    "run_python": 30000,     # max 12,177, and an agent-written aggregation can be much larger
    "ctf_lines": 42000,      # raw TCP lines are fat; measured max 37,512
    "query_ctf": 20000,      # max 2,485
    "ctf_timeline": 20000,   # max 201
}

_TRUNC_NOTE = (
    "Rows were dropped to fit the reply limit. They are in the order the tool produced them, "
    "so what is missing is the tail, not a random sample. If what you need might be among the "
    "dropped rows, narrow the time range or add a filter and call this tool again. Do not treat "
    "a missing row as evidence that nothing is there."
)


def fit_result(obj, cap: int):
    """Shrink a tool result to `cap` characters without breaking JSON or silently losing a key.

    Trims the longest list fields by dropping whole rows, then grows them back as far as the
    budget allows, and records what was dropped under `_truncated` so the model can tell a
    subset from a complete answer. Returns (text, truncated, dropped_or_None).
    """
    full = json.dumps(obj, default=str)
    if len(full) <= cap:
        return full, False, None

    def prefix():
        # last resort: nothing row-shaped to trim. Keep the payload VALID json and label it.
        return (json.dumps({"_truncated_prefix": full[:max(0, cap - 400)],
                            "_note": "Result too large to send whole and it has no row list to "
                                     "trim, so this is a PREFIX of the JSON and is not itself "
                                     "complete. Narrow your query and call again."},
                           default=str), True, {"_prefix": True})

    if not isinstance(obj, dict):
        return prefix()
    rows = {k: v for k, v in obj.items() if isinstance(v, list) and len(v) > 1}
    if not rows:
        return prefix()

    def render(keep):
        t = dict(obj)
        dropped = {}
        for k, n in keep.items():
            t[k] = obj[k][:n]
            if n < len(rows[k]):
                dropped[k] = {"shown": n, "total": len(rows[k])}
        if dropped:
            t["_truncated"] = {"dropped": dropped, "note": _TRUNC_NOTE}
        return json.dumps(t, default=str), dropped

    keep = {k: len(v) for k, v in rows.items()}
    # halve whichever list currently costs the most, until the whole thing fits
    for _ in range(400):
        text, dropped = render(keep)
        if len(text) <= cap:
            break
        k = max(keep, key=lambda k: len(json.dumps(obj[k][:keep[k]], default=str)))
        if keep[k] <= 1:
            return prefix()
        keep[k] //= 2
    else:
        return prefix()
    # halving overshoots, so give each list back as many rows as still fit
    for k in sorted(keep, key=lambda k: -len(rows[k])):
        lo, hi = keep[k], len(rows[k])
        while lo < hi:
            mid = (lo + hi + 1) // 2
            trial = dict(keep)
            trial[k] = mid
            if len(render(trial)[0]) <= cap:
                lo = mid
            else:
                hi = mid - 1
        keep[k] = lo
    text, dropped = render(keep)
    return text, bool(dropped), (dropped or None)


# fault vocabulary the agent must choose from (aligns with ground_truth families for scoring)
FAULT_TYPES = [
    "cpu_saturation", "memory_pressure", "disk_io", "network_latency", "db_latency",
    "dependency_outage", "error_storm", "noisy_neighbor", "cpu_throttling",
    "memory_limit", "service_network", "queue_backlog", "normal",
    # Added 29-09 after conn_pool_exhaustion scored 0/60: there was no word for it, so the
    # agent said "other" 33 times and was marked wrong every time. A label the agent cannot
    # utter makes the tally meaningless.
    "conn_pool_exhaustion", "deadlock", "lock_contention", "priority_inversion",
]

FAULT_VOCAB = (
    "FAULT TYPES (operational definitions — pick the closest):\n"
    "- cpu_saturation: host-wide CPU pressure; an extra workload or spike consumes host CPU, many "
    "services see contention.\n"
    "- noisy_neighbor: a co-tenant workload consumes host resources while user-facing KPIs stay "
    "near-normal; contention shows mainly in kernel scheduling signals.\n"
    "- disk_io: host disk saturated (host io_time / block latency up, all disk users affected).\n"
    "- memory_pressure: host memory exhausted (reclaim/writeback activity, available memory "
    "collapsing, swap).\n"
    "- network_latency: host-wide network delay/loss (cross-service calls slow everywhere, no "
    "single culprit path).\n"
    "- db_latency: a DATASTORE answers slowly (callers slow on DB calls; the datastore shows "
    "external/IO wait or induced latency WITHOUT cpu/memory saturation). Prefer this over "
    "dependency_outage when the slow component is a database and traffic still succeeds.\n"
    "- dependency_outage: a dependency is DOWN or FROZEN — calls to it hang to timeout or fail "
    "with connection errors and it produces little/no successful traffic (not merely slow).\n"
    "- error_storm: a service returns bursts of application errors/5xx; latency only moderately "
    "affected.\n"
    "- cpu_throttling: ONE service pinned by its CPU limit (its throttled-seconds jump; only it "
    "slows).\n"
    "- memory_limit: ONE service hits its memory cap (GC pressure/OOM kills/restarts at a flat "
    "memory ceiling).\n"
    "- service_network: ONE service's network path is degraded (only traffic through it is "
    "slow/lossy; host network fine).\n"
    "- queue_backlog: an async queue/consumer silently backs up (producer healthy, consumer "
    "idle/lagging, backlog grows; few user-visible errors).\n"
    "- normal: no injected fault evident.\n"
    "\n"
)

# The kernel-only system prompt. The agent is handed a raw LTTng kernel trace and nothing
# else - no alert, no incident window, no baseline. agent_v2 patches the tool count and
# enumeration in this text (and asserts on the exact wording), so CHANGING A WORD HERE IS A
# BREAKING CHANGE - run agent_v2's asserts after any edit.
KO_HEAD = (
    "You are a senior SRE handed ONE raw kernel trace from a microservice host. Nobody has "
    "told you whether anything went wrong, when, or where. There is no alert, no known "
    "incident window, and no pre-computed baseline. Finding all of that is the job.\n"
    "\n"
    "YOUR ONLY EVIDENCE is the LTTng kernel trace, through six tools. Three count things: "
    "ctf_timespan (how long the recording is), ctf_timeline (one event counted across the "
    "whole recording, bucketed, as a bar chart) and query_ctf (counts, rates and the "
    "processes responsible, over a range YOU choose). Two look at WHO rather than how much: "
    "ctf_proclife (when each process first and last appears) and ctf_procdiff (which "
    "processes differ between two ranges you pick). One shows the raw record: ctf_lines "
    "(real event lines with all their fields, over a narrow range). There are deliberately "
    "no metrics, logs or spans. That is the dataset, not a gap in it: never treat a missing "
    "modality as evidence that nothing happened.\n"
    "\n"
    "WHAT A PROCESS NAME DOES AND DOES NOT TELL YOU. Every event carries a pid_ns, and one "
    "pid_ns is one container. The same procname under two different pid_ns values is two "
    "different containers, so a runtime name - java, node, python3 - is almost never one "
    "thing: this host runs several Java services and the kernel calls every one of them "
    "`java`. If you answer with a bare runtime name you have found a signal and have NOT "
    "said where it is. Use pid_ns to separate them, and say which pid_ns you mean. You will "
    "not be able to read a service NAME out of the trace - the kernel does not record one - "
    "so identifying the specific container, and describing what it runs and how it behaves, "
    "is the most precise honest answer available. That is far better than falling back to "
    "`host`, which claims the whole machine is at fault.\n"
    "\n"
    "TWO KINDS OF CHANGE, AND YOU MUST CHECK BOTH. A problem can show up as a change in HOW "
    "MUCH is happening - event rates step up or collapse - or as a change in WHO is doing "
    "it, where a process appears or disappears and the totals barely move. Searching only "
    "for the first kind is the commonest way to get this wrong, because when a heavy "
    "workload STOPS, the backlog drains and the totals jump: the biggest step in a count "
    "chart is often the RECOVERY, sitting just after the problem, not the problem itself. "
    "If your candidate window begins at a rise in totals, check what was happening just "
    "BEFORE that rise.\n"
    "\n"
    "METHOD:\n"
    "1. ORIENT: ctf_timespan first, so you know the real start and end. Every later range "
    "must sit inside it. Timestamps are UTC.\n"
    "2. WHO CHANGED: ctf_proclife across the whole recording. Any process present for only "
    "part of it marks two boundaries - when it arrived and when it left - and those are "
    "candidate incident edges that no count chart will show you. Plenty of short-lived "
    "processes are routine, so treat these as candidates, not findings.\n"
    "3. HOW MUCH CHANGED: ctf_timeline on a few unrelated events (for example sched_switch, "
    "sched_wakeup, block_rq_issue, net_dev_xmit) across the FULL span. A change in ONE series "
    "that the others do not share points at whatever produces that event. A change shared by "
    "ALL of them needs care, and the direction matters: everything RISING together is often "
    "just more work arriving, but everything FALLING together is not - a host starved of CPU, "
    "a saturated disk or a degraded network makes the whole machine do less, and a "
    "synchronised collapse followed by a synchronised recovery is a perfectly ordinary "
    "signature for a host-wide fault. Do not reject a candidate window merely because several "
    "event types move together; ask what else would explain them all moving at once, and say "
    "which explanation you chose and why.\n"
    "4. PIN IT DOWN: ctf_procdiff between a range you suspect and a range you believe is "
    "quiet. What is in one and absent from the other is the strongest single signal you "
    "have. Say which range you treated as quiet and why - if that range overlaps the "
    "problem, everything downstream of it is wrong.\n"
    "5. FIND THE WHY, from the mechanism the kernel actually recorded: on-CPU saturation "
    "(sched_switch churn, one process monopolising), CPU starvation (long sched_wakeup to "
    "sched_switch delay), disk wait (block_rq_issue/block_rq_complete latency), network "
    "(net_dev_xmit/netif_receive_skb), lock or futex contention, memory reclaim, or a "
    "process exiting and respawning. Read a few raw lines with ctf_lines before you commit "
    "- counts alone can mislead.\n"
    "6. CONFIRM OR REJECT: state which check would have falsified your conclusion and "
    "whether you ran it. If the evidence genuinely shows a healthy system, say so - but "
    "only after looking across the whole span, not because a tool came back empty.\n"
    "7. Then submit_diagnosis, with the window you derived and the evidence for it.\n"
    "\n"
)

KO_RULES = (
    "RULES: root_cause_service is the culprit as it appears in the kernel trace - the process "
    "or container name itself when one workload is responsible, or 'host' for a host-wide "
    "resource cause with no single visible culprit. Kernel process names are truncated to 15 "
    "characters; report what you saw. Distinguish victims (processes waiting) from the culprit "
    "(the process consuming). incident_window must come from your own evidence: an invented "
    "window is worse than 'unknown'. Never guess a fault type before you have located a change "
    "in time and attributed it to a process."
)

_SUBMIT_DEF = {
    "name": "submit_diagnosis",
    "description": ("Commit the final verdict: WHAT went wrong, WHERE, and WHEN. The window is "
                    "part of the answer, not a detail - you were not told when the incident "
                    "was and finding it is half the job."),
    "parameters": {"type": "object", "properties": {
        # Free text FIRST, and it is the field a human actually reads. The enum below is a
        # convenience for tallying, not the answer.
        "what_is_wrong": {"type": "string", "description":
                          "In your own words, 1-3 plain sentences: what is happening, to what, "
                          "and why you think so. Do not just repeat the fault_type label. If "
                          "nothing appears wrong, say that and why."},
        # A process name is not a location. Measured on the svc_net blueprint-v4 run: the
        # agent computed the per-container ranking in 6 of 6 given-arm cells and then answered
        # `java` or `host`. When the culprit is a container, the pid_ns is required.
        "root_cause_service": {"type": "string", "description":
                               "WHERE the problem comes from, named as it appears in the "
                               "trace. If you have narrowed it to ONE container, you MUST "
                               "give its pid_ns - write it as 'procname in pid_ns NNNNNNNNNN'. "
                               "A bare runtime name like 'java' or 'node' does NOT locate "
                               "anything, because several different services run under each "
                               "of those names. Use 'host' only when the cause is host-wide "
                               "with no single culprit container. Kernel process names are cut "
                               "to 15 characters - give what you saw."},
        "culprit_kind": {"type": "string",
                         "enum": ["process", "container", "service", "host", "unknown"],
                         "description": "what kind of thing you just named. Use 'container' "
                                        "only if root_cause_service carries a pid_ns."},
        # "other" is allowed: the fixed list was written for a four-modality view and some of
        # its distinctions are not separable from a kernel trace alone. A wrong label hides a
        # correct understanding; what_is_wrong is what gets read.
        "fault_type": {"type": "string", "enum": list(FAULT_TYPES) + ["other"],
                       "description": ("closest match from the list. Pick 'other' if none of "
                                       "them fits what you actually saw - that is not a "
                                       "failure, and what_is_wrong is where you say what it "
                                       "was.")},
        "evidence": {"type": "string", "description":
                     "How you found it: which tool calls, which ranges you compared, and what "
                     "the decisive numbers were. Someone should be able to repeat your steps."},
        "confidence": {"type": "number", "description": "0..1"},
        # WHEN. Nothing told the agent this; it has to be derived from the trace, which is why
        # window_evidence is required alongside it - a guessed range that happens to overlap
        # is not a finding, and the two fields together let a human tell them apart.
        "incident_window": {"type": "string", "description":
                            "the time range the anomaly occupies, as 'HH:MM:SS - HH:MM:SS' in "
                            "trace clock time. Say 'unknown' if the evidence does not support "
                            "a range - a wrong window is worse than an admitted gap."},
        "window_evidence": {"type": "string", "description":
                            "what made you choose that range: which event, which tool call, "
                            "what changed at the boundary"}},
        "required": ["what_is_wrong", "root_cause_service", "culprit_kind", "fault_type",
                     "evidence", "confidence", "incident_window", "window_evidence"]},
}

KERNEL_ONLY_TOOLS = ("ctf_timespan", "ctf_timeline", "query_ctf", "ctf_lines",
                     "ctf_procdiff", "ctf_proclife", "submit_diagnosis")


def tool_defs():
    """The kernel-only tool schemas: the six raw-trace tools plus submit_diagnosis."""
    return [dict(t) for t in (_CTF_TIMESPAN_DEF, _CTF_TIMELINE_DEF, _CTF_TOOL_DEF,
                              _CTF_LINES_DEF, _CTF_PROCDIFF_DEF, _CTF_PROCLIFE_DEF,
                              _SUBMIT_DEF)]


def unmask_diagnosis(diagnosis, guard, tr=None):
    """Bring a submitted verdict back to real names."""
    if diagnosis is None or not config.MASK_NAMES:
        return diagnosis
    submitted = json.loads(json.dumps(diagnosis, default=str))
    diagnosis["root_cause_service"] = guard.unmask(diagnosis.get("root_cause_service"))
    diagnosis["evidence"] = guard.unmask_text(diagnosis.get("evidence"))
    if tr is not None and submitted != diagnosis:
        tr.event("unmask", submitted=submitted, unmasked=diagnosis, mapping=guard.mapping())
    return diagnosis


# transient provider failures worth retrying: rate limits, 5xx, timeouts, and the Azure/OpenAI
# reasoning-model "invalid_prompt" policy flag (fires intermittently on telemetry-heavy turns —
# an identical retry usually passes). Persistent failures still raise → recorded as an error row.
_RETRYABLE = ("429", "rate limit", "rate_limit", "500", "502", "503", "504", "timeout",
              "overloaded", "invalid_prompt")


class ProviderError(RuntimeError):
    """A provider returned 200 with an error body instead of a completion.

    OpenRouter does this for rate limits and upstream failures: HTTP is fine, `choices` is null
    and the real status sits in `error.code`. The SDK cannot raise on that, so nothing retried
    and a whole 120-cell matrix died on 'NoneType is not subscriptable'. Raising here puts it
    back on the path api_call already handles.
    """


def checked(r):
    """Return the response, or raise if the provider smuggled an error into a 200."""
    if getattr(r, "choices", None):
        return r
    err = getattr(r, "error", None) or {}
    if not isinstance(err, dict):
        err = {"message": str(err)}
    raise ProviderError("provider returned no choices: code=%s %s"
                        % (err.get("code"), str(err.get("message"))[:200]))


def api_call(call, tr, step, tries: int = 6):
    """Call the provider with retries on the transient failures in _RETRYABLE."""
    for attempt in range(tries):
        try:
            return call()
        except Exception as e:
            msg = repr(e).lower()
            if attempt == tries - 1 or not any(t in msg for t in _RETRYABLE):
                raise
            tr.event("api_retry", step=step, attempt=attempt + 1, error=repr(e)[:300])
            # A TOKEN rate limit is a budget refilling over about a minute, not a momentary
            # blip: 2/4/8 s put all three retries inside the same exhausted window and every
            # one failed. Back off on a scale that can outlast the limit.
            rate = "429" in msg or "rate limit" in msg or "rate_limit" in msg
            time.sleep((20 * 2 ** attempt) if rate else (2 * 2 ** attempt))


def run_tool(run_dir: str, name: str, args: dict):
    """Dispatch one kernel-trace tool against the run directory. Returns (result, bytes).

    procname is a kernel comm, not a service alias, so nothing here is unmasked - leakguard
    aliases services; the trace records the process names the kernel saw.
    """
    if name == "ctf_timespan":
        # LTTng layouts differ per collector (kernel/kernel vs trace/kernel) - find the
        # folder that holds `metadata` instead of assuming the StrataTrace layout.
        sub = "kernel/kernel"
        for root, dirs, files in os.walk(run_dir):
            if "metadata" in files:
                sub = os.path.relpath(root, run_dir)
                break
        return ctf_tool.ctf_timespan(run_dir, ctf_subdir=sub), 0
    if name == "ctf_timeline":
        return ctf_tool.ctf_timeline(
            run_dir, event=args.get("event") or "",
            buckets=args.get("buckets", 30), procname=args.get("procname")), 0
    if name == "query_ctf":
        return ctf_tool.query_ctf(
            run_dir, event=args.get("event") or "",
            begin=args.get("begin"), end=args.get("end"),
            buckets=args.get("buckets") or 0,
            procname=args.get("procname")), 0
    if name == "ctf_lines":
        return ctf_tool.ctf_lines(
            run_dir, event=args.get("event") or "",
            begin=args.get("begin") or "", end=args.get("end") or "",
            n=args.get("n", 10), procname=args.get("procname"),
            contains=args.get("contains")), 0
    if name == "ctf_procdiff":
        return ctf_tool.ctf_procdiff(
            run_dir,
            begin_a=args.get("begin_a") or "", end_a=args.get("end_a") or "",
            begin_b=args.get("begin_b") or "", end_b=args.get("end_b") or "",
            event=args.get("event") or ".", top=args.get("top") or 20), 0
    if name == "ctf_proclife":
        return ctf_tool.ctf_proclife(
            run_dir, min_events=args.get("min_events") or 1000,
            event=args.get("event") or "."), 0
    return {"error": f"unknown tool {name}"}, 0
