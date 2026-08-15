#!/usr/bin/env python3
"""Skill registry + evidence-driven selector — the v4 skill layer (new_design.md §5).

A skill is ONE markdown file in skills/: simple `key: value` frontmatter between `---`
lines, then three sections: `## Problem signature`, `## Investigation blueprint`,
`## Resolution template`. `covers: <fault_family>` is harness metadata (drives the
LOFO condition and selection scoring) and is NEVER shown to the model.

Selection is two-mode (leak discipline):
  * evaluation mode (this module): the ONLY selector input is the masked Phase-1
    evidence survey — nothing states the problem. The selector may ABSTAIN; abstaining
    falls back to the generic first-principles method (frozen v3).
  * assistant mode (future): `user_triggers` may match the user's own problem statement.

Registry lint: evaluation-grade skills must be service-agnostic — bodies may use the
fault-taxonomy vocabulary (it is the answer space, static for every incident) but must
not name services, containers, apps, or run ids of the benchmark.
"""
from __future__ import annotations
import glob
import json
import os
import re
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DIR = os.path.join(HERE, "skills")

# benchmark-specific identifiers a service-agnostic skill must never contain
_FORBIDDEN = [
    # injection infrastructure
    "anomaly-cpu-stress", "anomaly-mem-stress", "anomaly-disk-stress", "noisy-neighbor",
    "toxiproxy", "aggressor", "stress-ng",
    # Sock Shop services / apps
    "carts", "catalogue", "orders", "payment", "shipping", "queue-master", "rabbitmq",
    "front-end", "edge-router", "sock shop", "sockshop",
    # Train Ticket services / apps
    "mysql", "nacos", "train ticket", "trainticket",
    # ground-truth vocabulary
    "ground_truth", "target_service", "expected_blast_radius", "expected_winning_modality",
    "injection_start", "injection_end", "blind_spot",
]
_FORBIDDEN_RE = re.compile(
    "|".join([r"\bts-[a-z0-9-]*service\b", r"\buser-db\b"] +
             [re.escape(t) for t in sorted(_FORBIDDEN, key=len, reverse=True)]),
    re.IGNORECASE)


@dataclass
class Skill:
    name: str
    covers: str                      # fault family (harness metadata; not shown to the model)
    path: str
    version: str = "1"
    authored_by: str = "human"
    user_triggers: list = field(default_factory=list)   # assistant mode only
    signature: str = ""              # '## Problem signature' section (selector sees this)
    body: str = ""                   # full markdown body (injected on selection)


def _parse(path: str) -> Skill:
    text = open(path, encoding="utf-8").read()
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{path}: missing frontmatter")
    front, body = m.group(1), m.group(2).strip()
    meta = {}
    for line in front.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    for req in ("name", "covers"):
        if not meta.get(req):
            raise ValueError(f"{path}: frontmatter missing '{req}'")
    sections = {}
    for sec in re.split(r"^## +", body, flags=re.M):
        if not sec.strip():
            continue
        title, _, rest = sec.partition("\n")
        sections[title.strip().lower()] = rest.strip()
    sig = sections.get("problem signature", "")
    if not sig:
        raise ValueError(f"{path}: missing '## Problem signature' section")
    trig = [t.strip() for t in meta.get("user_triggers", "").split("|") if t.strip()]
    return Skill(name=meta["name"], covers=meta["covers"], path=path,
                 version=meta.get("version", "1"), authored_by=meta.get("authored_by", "human"),
                 user_triggers=trig, signature=sig, body=body)


def lint(skill: Skill) -> list:
    """Benchmark-identifier violations in the model-visible parts (signature + body)."""
    hits = sorted({m.group(0).lower() for m in _FORBIDDEN_RE.finditer(skill.body)})
    return [f"{skill.name}: forbidden token {h!r}" for h in hits]


def load_skills(skills_dir: str | None = None, strict: bool = True) -> list:
    """Load, parse, and lint every skills/*.md. strict=True refuses a dirty library."""
    d = skills_dir or DEFAULT_DIR
    out, problems = [], []
    for p in sorted(glob.glob(os.path.join(d, "*.md"))):
        if os.path.basename(p).upper().startswith("README"):
            continue
        s = _parse(p)
        problems += lint(s)
        out.append(s)
    names = [s.name for s in out]
    if len(set(names)) != len(names):
        problems.append(f"duplicate skill names: {names}")
    if problems and strict:
        raise ValueError("skill library failed lint:\n  " + "\n  ".join(problems))
    return out


# ---- evidence-driven selection (one structured LLM call) ---------------------------------
_SELECT_SYSTEM = (
    "You route incidents to investigation skills. You are given (1) an evidence survey of an "
    "incident — baseline vs incident-window changes across traces, topology, logs, metrics and "
    "kernel — and (2) the problem signatures of the available skills. Choose the SINGLE skill "
    "whose signature the evidence clearly matches, or abstain. Abstain when no signature clearly "
    "fits: a wrong skill misleads the investigation and is worse than none."
)

_SELECT_TOOL = {
    "name": "select_skill",
    "description": "Commit the routing decision.",
    "parameters": {"type": "object", "properties": {
        "skill_name": {"type": "string",
                       "description": "exact name of the chosen skill, or 'none' to abstain"},
        "confidence": {"type": "number", "description": "0..1"},
        "reason": {"type": "string", "description": "one sentence: the decisive evidence match"}},
        "required": ["skill_name", "confidence", "reason"]}}


def select(evidence_json: str, skills: list) -> dict:
    """Pick a skill (or abstain) from MASKED evidence only. Returns
    {skill: Skill|None, skill_name, confidence, reason, tokens{in,out}, prompt}."""
    import config
    listing = "\n\n".join(
        f"[{i + 1}] {s.name}\n{s.signature}" for i, s in enumerate(skills))
    user = (f"INCIDENT EVIDENCE (baseline vs incident survey):\n{evidence_json}\n\n"
            f"AVAILABLE SKILLS:\n{listing}\n\n"
            f"Call select_skill with the best-matching skill name, or 'none' to abstain.")
    turn = config.chat(_SELECT_SYSTEM, [{"role": "user", "content": user}], tools=[_SELECT_TOOL])
    args = {}
    if turn.tool_calls:
        raw = turn.tool_calls[0].get("arguments")
        args = raw if isinstance(raw, dict) else _json_or_empty(raw)
    else:
        args = _json_or_empty(turn.text)
    name = str(args.get("skill_name", "none")).strip()
    chosen = next((s for s in skills if s.name == name), None)
    return {"skill": chosen, "skill_name": chosen.name if chosen else "none",
            "confidence": args.get("confidence"), "reason": args.get("reason"),
            "tokens": {"in": turn.input_tokens, "out": turn.output_tokens},
            "prompt": {"system": _SELECT_SYSTEM, "user": user}}


def _json_or_empty(s):
    try:
        m = re.search(r"\{.*\}", s or "", re.S)
        return json.loads(m.group(0)) if m else {}
    except (json.JSONDecodeError, AttributeError):
        return {}


if __name__ == "__main__":
    lib = load_skills(strict=False)
    for s in lib:
        errs = lint(s)
        print(f"{s.name:32s} covers={s.covers:20s} triggers={len(s.user_triggers)} "
              f"{'LINT:' + str(len(errs)) if errs else 'clean'}")
        for e in errs:
            print("   ", e)
    print(f"\n{len(lib)} skills loaded")
