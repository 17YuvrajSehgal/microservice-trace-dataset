# RCA skill library (v4 — DRAFT, not yet wired into the harness)

One markdown file per skill. A skill is procedural RCA knowledge for one problem class:
what it looks like in **evidence** (problem_signature), how to **investigate** it
(blueprint), and how to **decide** the verdict (resolution template). Design and
evaluation protocol: `../../new_design.md` §5–§6.

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
