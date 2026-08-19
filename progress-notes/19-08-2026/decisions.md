## Mahsa Q&A -> paper/answers.md (2026-08-19)
Wrote paper/answers.md answering Mahsa's 12 review points on the supervisor report.
Answerable NOW from recorded data: component census (SS 14 app containers = 8 svc +
4 DB + rabbitmq + edge-router; TT ~67 total, shared MySQL); fault-target breakdown
(service-targeted localized 9/10 vs non-service components 1/3 -> blind-spot thesis
confirmed in agent results); baselines-under-degradation already run (1,395 evals
each: statistical 38->34 on traces, mmbaro flat 48; kernel features change nothing);
"not more data" control = minimal-budget agent 83% > baselines 46-48% at full data.
New experiments proposed (cheap, recorded-data only): LLM-only no-tool baseline
(prompt per Ahmed et al. ICSE'23 for defensibility), forced-guide cross matrix
(specificity), ranked top-1/3/5 answers + MRR/hit@k/P@k/MAP (evidence-ranked list +
self-consistency variant to address LLM-ranking-semantics concern). VM-dependent
(GCP billing off): code-mutation faults (must manifest in telemetry), multi-fault
recordings (set-aware scoring). Explicitly not pursuing modality-fusion direction
per Mahsa.
