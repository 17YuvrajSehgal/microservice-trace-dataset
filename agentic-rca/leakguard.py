#!/usr/bin/env python3
"""Anti-leakage guard — stops the agent being told the answer by naming conventions.

Two label-leak channels exist in any injected-fault dataset and both are closed here:
  1. Run IDs encode the fault ("tt_slow_db_aggressive_steady_r1") → the agent is given an
     opaque alias ("incident-3fa2b1c9") instead (see agent.py).
  2. Injection tooling names its containers after the fault (anomaly-cpu-stress,
     noisy-neighbor, toxiproxy) → Guard.mask_obj() pseudonymizes fault-vocabulary
     container/service identifiers in every tool result BEFORE it reaches the model
     ("container-a1b2c3", deterministic sha1 so the alias is stable within and across runs).

What is deliberately NOT masked (documented realism boundary, not a leak):
  * real service names (mysql, catalogue, ts-order-service) — they are the answer space;
  * long free-text log/digest lines — only exact known injection names are substring-replaced
    there; process signatures like "stress-ng" remain, because seeing a co-tenant's processes
    is legitimate SRE evidence (it reveals a synthetic workload, not which fault was injected);
  * the incident window — the standard "an alert fired at [t0,t1]" RCA assumption.

The agent answers in alias space; unmask() translates back before scoring, so scoring and
the non-LLM baselines are untouched. Toggle: RCA_MASK_NAMES=0 (config.py) — keeping the
unmasked condition runnable lets us QUANTIFY how many points the naming giveaway is worth.
Verification: audit_leakage.py scans finished transcripts for leak tokens.
"""
from __future__ import annotations
import hashlib
import re

# exact injection-infrastructure names (both apps share the fault recipes)
KNOWN_BAD = [
    "anomaly-cpu-stress", "anomaly-mem-stress", "anomaly-disk-stress",
    "noisy-neighbor", "toxiproxy",
]
# any identifier-shaped token built from fault vocabulary (catches compose-prefixed variants)
_VOCAB = re.compile(
    r"(?i)^[\w.-]{0,60}(stress|neighbor|aggressor|chaos|inject|anomaly|toxiproxy)[\w.-]{0,60}$")
# free-text substring replacement is restricted to the exact known names (never mangles prose)
_KNOWN_SUB = re.compile("|".join(re.escape(k) for k in sorted(KNOWN_BAD, key=len, reverse=True)),
                        re.IGNORECASE)

_IDENT_MAX = 80          # identifiers are short; longer strings are prose → substring rule only


def alias_run(run_id: str) -> str:
    """Opaque, deterministic incident alias shown to the model instead of the run id."""
    return "incident-" + hashlib.sha256(run_id.encode()).hexdigest()[:8]


class Guard:
    """Per-diagnosis pseudonymizer. mask_obj() walks a tool result; unmask() reverses the
    agent's answer (and evidence text) back to real names for scoring/reporting."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._fwd: dict[str, str] = {}
        self._rev: dict[str, str] = {}

    @staticmethod
    def _canon(name: str) -> str:
        """Canonical class for aliasing. The modalities use DIFFERENT names for the injected
        workload (kernel L1 says 'aggressor', metrics says 'anomaly-cpu-stress'): hashing raw
        names would fragment one entity into several pseudonyms and destroy cross-tool identity
        — information the unmasked names did carry. There is at most one injected workload per
        run, so the whole vocab class shares one alias; toxiproxy (a permanent proxy, present in
        normal runs too) is a distinct entity and keeps its own."""
        return "__proxy__" if "toxiproxy" in name.lower() else "__external_workload__"

    def _alias(self, name: str) -> str:
        if name not in self._fwd:
            canon = self._canon(name)
            a = "container-" + hashlib.sha1(canon.encode()).hexdigest()[:6]
            self._fwd[name] = a
            self._rev.setdefault(a, name)      # first-seen real name of the class, for unmask
        return self._fwd[name]

    def _mask_str(self, s: str) -> str:
        if len(s) <= _IDENT_MAX and (_VOCAB.match(s) or s.lower() in KNOWN_BAD):
            return self._alias(s)
        return _KNOWN_SUB.sub(lambda m: self._alias(m.group(0).lower()), s)

    def mask_obj(self, o):
        """Recursively pseudonymize identifiers in a tool result (dict keys + string values)."""
        if not self.enabled:
            return o
        if isinstance(o, str):
            return self._mask_str(o)
        if isinstance(o, dict):
            return {(self._mask_str(k) if isinstance(k, str) else k): self.mask_obj(v)
                    for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [self.mask_obj(x) for x in o]
        return o

    def unmask(self, name):
        """Alias → real name (identity for anything we never masked)."""
        if not isinstance(name, str):
            return name
        return self._rev.get(name, name)

    def unmask_text(self, text):
        """Replace every alias occurring inside free text (e.g. the evidence sentence)."""
        if not isinstance(text, str) or not self._rev:
            return text
        for a, real in self._rev.items():
            text = text.replace(a, real)
        return text

    def mapping(self) -> dict:
        return dict(self._fwd)
