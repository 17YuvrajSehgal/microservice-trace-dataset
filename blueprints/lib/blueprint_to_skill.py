#!/usr/bin/env python3
"""Generate an agent skill from a blueprint, and validate the blueprint first.

A blueprint is the human-facing, reviewable record of one solved investigation. A skill is
what the agent is actually handed. Generating one from the other means the two can never
drift, and it is the reason the blueprint is the artifact we maintain.

Leakage: fields listed under `harness_only` (labelled run ids) and `decision.fault_type`
carry the answer. They are used for scoring and are NEVER written into the skill body.

    python3 blueprint_to_skill.py --validate blueprints/*.json
    python3 blueprint_to_skill.py --out agentic-rca/skills-generated blueprints/*.json
"""
from __future__ import annotations
import argparse, glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

# Words that would hand the agent the answer if they appeared in the skill body.
LEAK_TOKENS = ["noisy_neighbor", "slow_db", "anomaly_cpu", "anomaly_mem", "anomaly_disk",
               "anomaly_net", "svc_cpu_cap", "svc_mem_cap", "svc_net", "queue_backlog",
               "error_storm", "dependency_outage", "aggressive", "subtle", "_r1", "_r2", "_r3",
               "sockshop", "trainticket", "anomaly-cpu-stress", "noisy-neighbor"]

REQUIRED = ["id", "version", "problem", "reproduction", "collection_order",
            "processing", "outputs", "decision", "provenance"]

PROVIDERS = os.path.join(os.path.dirname(HERE), "providers.json")
THRESHOLDS = os.path.join(os.path.dirname(HERE), "thresholds.json")


def load_thresholds():
    """name -> {value, unit, transfers, measured, used_by}. The single source for every
    number a blueprint decides on. Blueprints quote these by {NAME} rather than writing the
    figure, so the document and blueprint_decide.py cannot disagree."""
    try:
        with open(THRESHOLDS, encoding="utf-8") as fh:
            return json.load(fh).get("thresholds", {})
    except (OSError, json.JSONDecodeError):
        return {}


def fill_thresholds(text, th):
    """Substitute {NAME} with the measured value, for the agent-facing skill.

    The agent gets a real number - Mahsa's finding is that a description is not enough. The
    blueprint keeps the name, so editing thresholds.json moves every skill at once.

    The NUMBER only, never the unit: the sentence around it already says what the number
    counts, and appending the unit produced "450 requests/s per x of interrupt rise requests
    per second for each unit of rise in device interrupt time".
    """
    def one(m):
        t = th.get(m.group(1))
        if not t:
            return m.group(0)
        v = t["value"]
        return ("%g" % v) if isinstance(v, (int, float)) else str(v)
    return re.sub(r"\{([A-Z][A-Z0-9_]*)\}", one, text)


def load_providers():
    """capability id -> registry entry. A blueprint declares capabilities; this file binds
    them to whatever tool is actually available. Keeping that split is what makes the
    blueprint portable across tools instead of being a script wrapper."""
    try:
        with open(PROVIDERS, encoding="utf-8") as fh:
            return json.load(fh).get("capabilities", {})
    except (OSError, json.JSONDecodeError):
        return {}


def bind(cap_id, providers):
    """Resolve a capability to the first implemented provider. Returns (run, provider_id)."""
    cap = providers.get(cap_id)
    if not cap:
        return None, None
    for pr in cap.get("providers", []):
        if pr.get("status") == "implemented" and pr.get("run"):
            return pr["run"], pr["id"]
    return None, None


def validate(bp: dict, path: str) -> list:
    """Structural checks the schema cannot express, plus the ones that actually bite."""
    errs = []
    for k in REQUIRED:
        if k not in bp:
            errs.append(f"missing top-level field: {k}")
    if errs:
        return errs

    if not re.fullmatch(r"[a-z0-9-]+", bp["id"]):
        errs.append(f"id must be kebab-case: {bp['id']!r}")

    p = bp["problem"]
    if not p.get("discriminators"):
        errs.append("problem.discriminators is empty - a blueprint without discriminators "
                    "cannot be told apart from its look-alikes")
    for i, d in enumerate(p.get("discriminators", [])):
        for f in ("signal", "this_problem", "not_this_problem"):
            if not d.get(f):
                errs.append(f"discriminator[{i}] missing {f}")
        # EVIDENCE-FIRST RULE: a discriminator is a research claim. It may only be stated
        # if it was measured on our data, and the measurement must be pointed at.
        if not d.get("evidence"):
            errs.append(f"discriminator[{i}] ({d.get('signal','?')}) has no `evidence` - "
                        "every discriminator must cite the measurement that proved it. "
                        "Measure first (lib/measure_wait_signature.py), then author.")
        elif not any(t in d["evidence"].upper() for t in ("MEASURED", "EVIDENCE/", "RESULTS/")):
            errs.append(f"discriminator[{i}] evidence does not reference a measurement or an "
                        "evidence/ results/ artifact: " + d["evidence"][:70])

    # A step declares a CAPABILITY, never a tool — that is what keeps the blueprint portable
    # (Naser's architecture). Binding must still resolve to a real command, so Mahsa's rule
    # holds where it matters: what reaches the agent is an exact callable, not a description.
    providers = load_providers()
    for i, s in enumerate(bp.get("processing", [])):
        cap, run = s.get("capability"), s.get("run", "")
        if not cap and not run:
            errs.append(f"processing[{i}] declares neither a `capability` nor a `run`")
        elif cap:
            if cap not in providers:
                errs.append(f"processing[{i}] needs capability {cap!r}, absent from providers.json")
            elif not bind(cap, providers)[0]:
                errs.append(f"processing[{i}] capability {cap!r} has no IMPLEMENTED provider — "
                            "the blueprint cannot execute in this environment")
        elif not re.match(r"^(python3?|bash|sh|babeltrace2|TZ=\S+|cp|grep|awk|\./|\S+\.sh)\b", run):
            errs.append(f"processing[{i}].run does not look like a command: {run[:60]!r}")
        if not s.get("produces"):
            errs.append(f"processing[{i}] does not say what it produces")
        # PORTABILITY, and a leak. A step may only ask for inputs an operator working a live
        # incident actually has: where the traces are, which window, where to write. It may
        # NOT ask for our dataset's coordinates - and <family> is the ground-truth fault name,
        # so requiring it both breaks deployment anywhere else AND hands the answer to the
        # model the harness is supposed to be testing.
        blob = json.dumps(s)
        for bad, why in (("<app>", "our dataset's application name"),
                         ("<run_id>", "our dataset's run identifier"),
                         ("<family>", "THE GROUND-TRUTH FAULT NAME - this is the answer"),
                         ("/scratch/", "a path on our cluster")):
            if bad in blob:
                errs.append(f"processing[{i}] requires {bad} ({why}). A blueprint may only "
                            "need <trace_dir>, <window> and <out>")

    for c in bp.get("capabilities_required", []):
        if c.get("id") not in providers:
            errs.append(f"capabilities_required lists {c.get('id')!r}, absent from providers.json")

    if not (bp.get("applicability") or {}).get("apply_when"):
        errs.append("no `applicability.apply_when` — a blueprint must say when it applies, or "
                    "a selector cannot choose it")
    if not (bp.get("stopping_conditions") or {}).get("conclude"):
        errs.append("no `stopping_conditions.conclude` — a blueprint must say when the "
                    "investigation is finished")

    # Every declared output should be produced by some step.
    produced = " ".join(str(s.get("produces", "")) for s in bp.get("processing", []))
    for o in bp.get("outputs", []):
        if o["path"] not in produced:
            errs.append(f"output {o['path']} is declared but no processing step produces it")

    if not bp["collection_order"].get("kernel_events"):
        errs.append("collection_order.kernel_events is empty - a blueprint must say exactly "
                    "what to record, not 'kernel data'")

    d = bp["decision"]
    if not d.get("rule_out"):
        errs.append("decision.rule_out is empty - a blueprint must say when NOT to conclude this")

    # ---- NO SILENT DRIFT BETWEEN THE DOCUMENT AND THE ENGINE ------------------------------
    # The numbers used to be written twice: as prose here, and as Python literals in
    # blueprint_decide.py. Nothing compared them, and they drifted badly - host-disk-saturation
    # still told a reader "at least 2000 disk requests per second" after the engine had
    # replaced that with a ratio, and service-memory-cap documented an IRQ_X=2.5 / 500 req/s
    # pair that the engine's own comment records as having scored 3/16 before replacement.
    # A reader following the blueprint was following a rule we had measured and rejected.
    #
    # Now a blueprint quotes a threshold by {NAME} and the value is substituted at generation
    # time from thresholds.json. These checks make the quoting mandatory and the names real.
    th = load_thresholds()
    used = d.get("uses_thresholds") or []
    for name in used:
        if name not in th:
            errs.append(f"decision.uses_thresholds names {name!r}, absent from thresholds.json")
        elif bp["id"] not in th[name].get("used_by", []):
            errs.append(f"threshold {name} does not list {bp['id']} in its used_by - "
                        "the two directions must agree or one of them is stale")
    prose = " ".join(list(d.get("verdict_when", []))
                     + [r.get("when", "") for r in d.get("rule_out", [])])
    for ref in set(re.findall(r"\{([A-Z][A-Z0-9_]*)\}", prose)):
        if ref not in th:
            errs.append(f"decision prose refers to {{{ref}}}, absent from thresholds.json")
        elif ref not in used:
            errs.append(f"decision prose refers to {{{ref}}} but uses_thresholds omits it")
    # A bare number where a threshold belongs is exactly how the last drift started, so the
    # rule here is blunt on purpose: in verdict_when, ANY digit must come from a {NAME}.
    # An earlier version of this check tried to match units ("N requests per second") and
    # missed the real bug, because the prose read "2000 disk requests per second" - one word
    # in the wrong place and the check was blind. Matching units is guesswork; matching digits
    # is not. rule_out stays lenient: it quotes other faults' measured ranges as context, and
    # those are descriptions rather than bars this blueprint applies.
    for i, v in enumerate(d.get("verdict_when", [])):
        if re.search(r"\d", re.sub(r"\{[A-Z][A-Z0-9_]*\}", "", v)):
            errs.append(f"decision.verdict_when[{i}] contains a bare number - every figure a "
                        f"blueprint decides on must be quoted as {{NAME}} from thresholds.json "
                        f"so it cannot drift from the engine: {v[:72]!r}")

    if str(bp["provenance"].get("verified_by", "")).startswith("PENDING"):
        errs.append("NOTE: not yet human-verified (provenance.verified_by is PENDING)")

    return errs


def _harness_leak_re():
    """The evaluation harness lints every skill it loads and REFUSES a dirty library. Keeping a
    second, private word list here was the bug: this file passed a skill the harness then
    rejected, and the whole with/without job died at load time. Borrow the harness list so the
    generator can never emit something the consumer will refuse."""
    try:
        sys.path.insert(0, os.path.join(ROOT, "agentic-rca"))
        import skillreg                                                    # noqa: PLC0415
        return skillreg._FORBIDDEN_RE
    except Exception:                                                      # noqa: BLE001
        return None                                    # harness absent — local list still applies


def leak_scan(text: str) -> list:
    low = text.lower()
    hits = {t for t in LEAK_TOKENS if t.lower() in low}
    rx = _harness_leak_re()
    if rx:
        hits |= {m.group(0).lower() for m in rx.finditer(text)}
    return sorted(hits)


def to_skill(bp: dict) -> str:
    """Render the agent-facing skill. Answer-bearing fields are deliberately excluded."""
    p, c, d = bp["problem"], bp["collection_order"], bp["decision"]

    app = bp.get("applicability", {})
    sig = ["## When this applies"]
    for x in app.get("apply_when", []):
        sig.append(f"- {x}")
    if app.get("do_not_apply_when"):
        sig.append("")
        sig.append("Do NOT use this blueprint when:")
        for x in app["do_not_apply_when"]:
            sig.append(f"- {x}")
    if app.get("cheap_precheck"):
        sig += ["", f"Cheapest check first: {app['cheap_precheck']}"]

    sig += ["", "## Problem signature"]
    for s in p["symptoms"]:
        sig.append(f"- {s}")
    sig.append("")
    sig.append("Telling it apart from its look-alikes:")
    for disc in p["discriminators"]:
        sig.append(f"- **{disc['signal']}** — this problem: {disc['this_problem']}. "
                   f"Not this problem: {disc['not_this_problem']}.")

    retracted = p.get("unverified_do_not_claim") or []

    order = ["## What to look at first",
             "The signals below are sufficient for this problem; you do not need everything.",
             ""]
    order.append(f"- kernel: {', '.join(c['kernel_events'])}")
    if c.get("metrics"):
        order.append(f"- metrics: {', '.join(c['metrics'])}")
    if c.get("traces"):
        order.append(f"- traces: {'; '.join(c['traces'])}")
    if c.get("logs"):
        order.append(f"- logs: {'; '.join(c['logs'])}")
    if c.get("why_these"):
        order += ["", f"Why this set: {c['why_these']}"]

    providers = load_providers()
    steps = ["## Investigation blueprint",
             "Each step names the capability it needs. The command shown is the binding "
             "resolved for THIS environment; another environment may bind a different tool "
             "to the same capability without changing the procedure.", ""]
    for i, s in enumerate(bp["processing"], 1):
        steps.append(f"{i}. {s['step']}")
        cap = s.get("capability")
        run = s.get("run")
        if cap:
            bound, prov = bind(cap, providers)
            steps.append(f"   needs: `{cap}`")
            if bound:
                steps.append(f"   run [{prov}]: `{bound}`")
            run = run or bound
        elif run:
            steps.append(f"   run: `{run}`")
        if s.get("expect"):
            steps.append(f"   expect: {s['expect']}")

    outs = ["## What to produce"]
    for o in bp["outputs"]:
        outs.append(f"- {o['kind']}: {o['contains']}")

    # The blueprint stores {NAME}; the agent is given the measured value. Keeping the name in
    # the document and the number in the skill is what stops the two from drifting apart.
    th = load_thresholds()
    res = ["## Resolution template", "Conclude this problem when ALL of:"]
    for v in d["verdict_when"]:
        res.append(f"- {fill_thresholds(v, th)}")
    res += ["", "Prefer a different explanation when:"]
    for r in d["rule_out"]:
        res.append(f"- {r['instead']} — {fill_thresholds(r['when'], th)}")
    res += ["", f"Root cause is: {d['root_cause_is']}"]

    stop = bp.get("stopping_conditions") or {}
    if stop:
        res += ["", "## When to stop"]
        if stop.get("conclude"):
            res.append(f"- Conclude when: {stop['conclude']}")
        if stop.get("stop_and_switch"):
            res.append(f"- Stop and switch: {stop['stop_and_switch']}")
        if stop.get("stop_insufficient"):
            res.append(f"- Evidence insufficient: {stop['stop_insufficient']}")
        if stop.get("max_evidence_rounds"):
            res.append(f"- Do not exceed {stop['max_evidence_rounds']} rounds of gathering "
                       "more evidence before reporting what is missing.")

    pol = bp.get("policies") or {}
    if pol:
        res += ["", "## Constraints you must respect"]
        if pol.get("collection_order_rule"):
            res.append(f"- {pol['collection_order_rule']}")
        if pol.get("max_collection_overhead_pct"):
            res.append(f"- Keep total added collection overhead under "
                       f"{pol['max_collection_overhead_pct']}%.")
        for x in pol.get("privacy", []):
            res.append(f"- {x}")
        appr = pol.get("approval") or {}
        if appr.get("requires_approval"):
            res.append("- These need human approval before you do them: "
                       + "; ".join(appr["requires_approval"]) + ".")

    suf = bp.get("evidence_sufficiency") or {}
    if suf:
        res += ["", "## If you are not confident enough"]
        if suf.get("confidence_floor"):
            res.append(f"- Do not report a diagnosis below {suf['confidence_floor']} confidence.")
        if suf.get("if_below_floor"):
            res.append(f"- {suf['if_below_floor']}")
        if suf.get("report_when_stuck"):
            res.append(f"- {suf['report_when_stuck']}")

    # How this problem looks on different system shapes. Measured on more than one
    # application, and kept as separate pictures rather than averaged into one threshold - a
    # number learned on one architecture does not describe another, and saying so is the
    # point of writing the blueprint down.
    scen = (bp.get("scenarios") or {}).get("cases") or []
    if scen:
        res += ["", "## How this looks on different systems",
                "The same fault does not look the same everywhere. Work out which case you are",
                "in before you judge the numbers."]
        for s in scen:
            res.append(f"\n**{s['scenario']}** — recognise by: {s['recognise_by']}")
            res.append(f"- What you see: {s['what_you_see']}")
            if s.get("confidence"):
                res.append(f"- How much to trust it: {s['confidence']}")
            if s.get("do_this_instead"):
                res.append(f"- Instead: {s['do_this_instead']}")

    adapt = bp.get("adaptation_rules") or []
    if adapt:
        res += ["", "## If the evidence does not fit"]
        for r in adapt:
            res.append(f"- If {r['if']}, then {r['then']}.")

    warn = []
    if retracted:
        warn = ["## Signals that do NOT work for this problem",
                "Each of these was measured on our own data and found unusable. Do not reason",
                "from them, and do not let their absence argue against this problem:"]
        for r in retracted:
            # `measurement` names fault families and is for the human record only; the skill
            # gets `agent_note`, which says the same thing without the answer vocabulary.
            warn.append(f"- {r['claim']} — **{r['status']}**. "
                        f"{r.get('agent_note') or ''}")

    body = "\n".join(sig + [""] + order + [""] + steps + [""] + outs + [""] + res
                     + ([""] + warn if warn else []))

    fm = [
        "---",
        f"name: {bp['id']}",
        f"version: {bp['version']}",
        f"authored_by: {bp['provenance']['authored_by']}",
        f"generated_from: blueprints/{bp['id']}.json",
        # No trailing comment here. skillreg parses frontmatter as split(":", 1) and keeps the
        # whole remainder, so an inline note becomes PART OF the value — `covers` then never
        # equals the ground-truth family and every selection scores wrong. (It is harness
        # metadata for scoring and LOFO, stripped before the model sees anything.)
        f"covers: {d.get('fault_type', '')}",
    ]
    if bp.get("mutually_exclusive_with"):
        fm.append(f"mutually_exclusive_with: {', '.join(bp['mutually_exclusive_with'])}")
    fm.append("---")

    return "\n".join(fm) + "\n" + body + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("blueprints", nargs="+")
    ap.add_argument("--out", default="", help="write skills here; omit to validate only")
    ap.add_argument("--validate", action="store_true")
    a = ap.parse_args()

    paths = []
    for pat in a.blueprints:
        paths += sorted(glob.glob(pat))
    if not paths:
        sys.exit("no blueprints matched")

    bad = 0
    for path in paths:
        try:
            bp = json.load(open(path, encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"FAIL {path}: invalid JSON: {e}"); bad += 1; continue

        errs = validate(bp, path)
        hard = [e for e in errs if not e.startswith("NOTE:")]
        for e in errs:
            print(("  WARN " if e.startswith("NOTE:") else "  ERR  ") + e)
        if hard:
            print(f"FAIL {path}: {len(hard)} problem(s)"); bad += 1; continue

        skill = to_skill(bp)
        # Scan the BODY only. The frontmatter carries `covers:` on purpose — it is harness
        # metadata for scoring and leave-one-out, and skillreg never puts it in the prompt.
        body_only = skill.split("---", 2)[-1]
        leaks = leak_scan(body_only)
        if leaks:
            print(f"FAIL {path}: skill body leaks answer tokens: {leaks}"); bad += 1; continue

        print(f"OK   {path}  ({len(bp['processing'])} steps, "
              f"{len(bp['collection_order']['kernel_events'])} kernel events, "
              f"{len(bp['problem']['discriminators'])} discriminators)")

        if a.out:
            os.makedirs(a.out, exist_ok=True)
            dst = os.path.join(a.out, bp["id"] + ".md")
            open(dst, "w", encoding="utf-8").write(skill)
            print(f"     -> {dst}")

    print(f"\n{len(paths) - bad}/{len(paths)} blueprints usable")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
