## Review items 1/3/8 implemented and run (2026-08-21) — a result that changes the framing

Cost $1.29, 115/115 transcripts auditor-PASS.

**Item 3 is the important one.** A model-only control (same model, same deterministic evidence
briefing, NO tool loop, one forced call) **ties the frozen 7-tool agent exactly: 78%/52% both
ways**, at 27% of the tokens and zero tool calls. A cruder raw-survey-dump control scores
83%/57%. The control is not a strawman — it gets the same briefing the agent gets. Conclusion:
**the deterministic evidence construction is doing the work, not the agentic loop**; 8-10 rounds
of querying rediscover what one good survey already contains. Honest limits: n=23 so one fault
= 4.3 pts ("indistinguishable", not "no-tools wins"); and the SAME frozen config scores 87%/57%
in the main campaign vs 78%/52% here — the +-9 noise band appearing in our own headline, which
is now the strongest argument that quoted numbers need repeats.

**Item 8**: ranked evidence-backed candidates lift fault typing 52->65% and localization 74->87%
at hit@3; hit@3 == hit@5 everywhere (nothing recovered by guess 4-5); model volunteers only
2.0-2.6 candidates of 5 allowed, so the evidence filter works rather than the model padding.

**Item 1**: component census grounded on meta/ container roster (first draft was inflated by
metric labels that are not containers: "Ubuntu", "scrape", "notify"). SS 16 components/6 with
spans; TT 46/36. **Every datastore in both apps is span-less; the kernel layer sees 4/4 and
2/3** — the blind-spot premise, measured.

**Engineering trap worth remembering:** all steps use grid=full, so they share the transcript
filename `<app>/<run>/full.json`; a shared --transcripts dir silently overwrote 69 of 92 audit
records on the first attempt (numbers survived, audit trail did not). Driver now gives each step
its own transcripts dir. Same class of bug as the earlier bundle_artifact arcname collision.

**Framing implication (flagged to Yuvraj, awaiting his call):** the agent is the instrument,
not the product. Sellable = (1) the dataset + kernel ladder, (2) the measurements — how little
telemetry is needed, partial-kernel worse than none, and now brief-matches-agent. Item 6
(forced-guide matrix) held back pending that decision.
