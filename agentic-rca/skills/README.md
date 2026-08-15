# RCA skill library (v4 — wired via skillreg.py; conditions via `evaluate.py --skills`; the
# selector routes on the Shared Investigation Context digest — see ../shared_context.py)

One markdown file per skill. A skill is procedural RCA knowledge for one problem class:
what it looks like in **evidence** (`## Problem signature` — the selector sees only
this), how to **investigate** it (`## Investigation blueprint`), and how to **decide**
the verdict (`## Resolution template`). On selection the full body is appended to the
system prompt with an explicit "abandon it if evidence contradicts it" instruction.
Design and evaluation protocol: `../../new_design.md` §5–§6.

File format (parsed by `skillreg.py` — no YAML dependency):

```
---
name: db-latency-rca
version: 1
authored_by: human
covers: slow_db                       # harness metadata: LOFO + selection scoring; NEVER shown to the model
user_triggers: database is slow | db latency    # '|'-separated; assistant mode only
---
## Problem signature
- topology: ...
## Investigation blueprint
1. ...
## Resolution template
- fault_type X when ...
```

Two ways a skill is selected:
- **Assistant mode**: the user's problem statement may match `user_triggers` (MVP-style).
- **Evaluation mode**: ONLY the Phase-1 evidence signature is matched against
  `problem_signature`; the selector may ABSTAIN, which falls back to the generic
  first-principles method (the frozen v3 prompt). Nothing may state the problem.

Authoring rules for evaluation-grade skills (linted by `audit_leakage.py` once wired):
1. **Service-agnostic**: "the converged-on datastore", never a concrete service name.
2. No run ids, app names, injected-container names, intensity/workload vocabulary.
3. Describe evidence patterns and decision boundaries, not expected answers for a
   specific benchmark incident.
4. Frontmatter: `name`, `version`, `authored_by` (`human` or `mined:<refs>`),
   `user_triggers` (assistant mode only), `problem_signature` (list of evidence
   patterns per modality).

Customer-authored skills in assistant mode MAY name their own services/systems — the
restrictions above exist to keep the *benchmark* honest, not to limit the product.
