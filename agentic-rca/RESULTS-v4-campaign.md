# v4 skill campaign — S0 / S0b / S1 / S2 over the 23 gate incidents (2026-08-16)

102 runs (4 conditions × 23 incidents + r=3 repeats on the 5 flip-prone pairs), leakage-masked,
fully transcripted, auditor **PASS on all 102**. Total cost **$1.80 at GPT-5-proxy rates**
(~$0.018/incident; 1.93M input, 50% cache-served, 48k output). Artifacts:
`/project/…/artifacts/artifact_campaign_20260816.tar.gz` (102 results + 102 transcripts,
sha256 manifest). Analysis scripts: `campaign_report.py`, `cost_report.py`.

## Headline

| Condition | Library / brief | service | fault | both | avg calls | input tokens | $/incident |
|---|---|---|---|---|---|---|---|
| **S0** — generic agent | none / no | 83% | 57% | 57% | 15.2 | 599k | $0.017 |
| **S0b** — Context Builder brief | none / yes | **87%** | **61%** | **57%** | **9.0** | **250k** | **$0.010** |
| **S1** — skills + brief | full / yes | 78% | 43% | 43% | 8.5 | 462k | $0.022 |
| **S2** — LOFO + brief | minus own family / yes | 70% | 39% | 39% | 8.6 | 446k | $0.021 |

## Finding 1 — the Context Builder is the validated win

S0b beats every other condition on service (87%) and fault (61%) while costing **58% fewer
input tokens and 41% fewer tool calls** than the plain agent. The deterministic Phase-1
survey + masked brief is the configuration of record going forward.

Note vs the frozen v3 gate (83/48/48): the v4 *generic tool upgrades alone* (peer-edge
topology, limit signals) lifted fault-typing 48%→57% before any skill or brief.

## Finding 2 — skills currently subtract, and the mechanism is precisely located

S1 underperforms the floor (43% vs 57% both) — **entirely on Train Ticket** (both 6/11 → 3/11;
Sock Shop unchanged 7/12, with `noisy_neighbor` actually FIXED only by its skill). Selection is
15/23, and the 8 wrong selections have one dominant signature: **db-latency-rca chosen 5×,
frozen-dependency 2×, on the shared-datastore app** — every TT service reaches mysql through
the proxy, so datastore edges appear in every survey and the selector latches on despite the
boundary text. Per-family, skill lift is real where selection is right (SS noisy_neighbor
s→Y; TT dependency_outage stable-Y ×3 repeats); wrong selections erase it elsewhere
(TT anomaly_cpu Y→., svc_mem_cap s→.).

**Conclusion: the skill CONTENT works; the evidence-only selector is the single blocking
component**, specifically against shared-datastore topologies. (Candidate fixes, future work:
two-stage selection that verifies discriminator checks against SIC claims before committing;
an architecture prior that discounts ubiquitous datastore edges; skipping injection below a
confidence threshold.)

## Finding 3 — the unseen-fault (S2) result is a legitimate negative

Abstention almost never happens (3/23) — with 11 adjacent skills present, something always
looks plausible. The agent's override ability limits the damage (19/23 incidents score the
same both-result as S0; 4 lost; 0 gained), but net: **an unseen fault under a full library
costs ~18 points versus the skill-free floor**. The pre-registered framing anticipated this:
"if S2 < S0, distractor skills actively mislead — an important negative result either way."
For the paper: today the honest deployment advice is S0b for unknown faults; skill libraries
need selection quality before they are safe on out-of-library incidents.

## Finding 4 — fault-label semantics account for much of the remaining fault gap

Across all conditions, the svc-right/fault-wrong rows concentrate on three label boundaries:
`error_storm`→dependency_outage ×7 (the agent accurately describes injected connection resets
toward the datastore), `noisy_neighbor`→cpu_throttling/saturation ×6 (the co-tenant is itself
CPU-capped), `svc_net`→db_latency ×4. A mechanism-correct secondary metric would credit most
of these; label-strict remains the primary score.

## Stability (r=3 repeats on flip-prone pairs)

TT dependency_outage: stable-correct in S1 AND S2 (3/3 each). TT slow_db: stable-WRONG under
S1 (0/3 — frozen-dependency selection consistently steers it; the earlier one-off success did
not reproduce). TT svc_cpu_cap S1: 2/3. SS svc_mem_cap brief: 2/3. Overall: repeats confirm
the flip-prone set is small and now quantified.

## Deployment recommendation (as of this campaign)

**Ship S0b** (Context Builder brief, no skills) as the default: best accuracy, lowest cost,
immune to selection error. Enable skills per-family only where selection is demonstrated
reliable (host anomalies, dependency_outage, svc_cpu_cap on SS-like topologies), or after a
selector redesign. All numbers above are leakage-controlled and reproducible from the archived
transcripts.
