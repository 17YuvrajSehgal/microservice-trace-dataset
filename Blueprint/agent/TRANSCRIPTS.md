# Agent transcripts — the publishable audit record

Every LLM-agent diagnosis produces one JSON transcript capturing **exactly what the
model was given and exactly what it produced**. Together with the results JSON these
are the artifact we ship with the paper: anyone can replay the agent's reasoning,
verify the numbers, and check that the agent never saw the ground truth.

## Where they come from

`evaluate.py --method agent` writes one transcript per **(incident × condition)** to
`<transcripts_dir>/<app>/<run_id>/<condition>.json` (default dir: `<out>_transcripts/`;
disable with `--transcripts none`). Each result row carries a `transcript` field with
the relative path; the results `meta` carries `transcripts_dir`, `git_commit`, `argv`,
and the full per-condition `DegradeSpec`. Capture is **logging-only**: it changes
neither the messages nor the API kwargs, so transcribed results are directly
comparable with earlier untranscribed runs.

## File shape

```json
{
  "meta":   { ...who/what/when/how... },
  "events": [ ...ordered conversation events... ],
  "final":  { "diagnosis": {...}, "stop_reason": "...", ...totals... }
}
```

### `meta`
| field | meaning |
|---|---|
| `schema_version` | transcript schema version (currently 1) |
| `run_id`, `condition`, `app`, `grid` | which incident, which degradation condition |
| `degrade_spec` | the full `DegradeSpec` fields for this condition |
| `provider`, `model`, `sdk` | e.g. `azure` / `gpt-5.4` / `openai` (never endpoints or keys) |
| `request_kwargs` | `max_tokens` + effective temperature policy (`"omitted"` when not sent) |
| `sent_cap_chars`, `max_steps` | tool-result truncation cap; loop step cap |
| `git_commit`, `python`, `host`, `stratatrace_app` | code + environment provenance |
| `started_utc`, `finished_utc` | wall-clock bounds |

### `events` (ordered; `i` = index, `t` = UTC timestamp)
| type | contents |
|---|---|
| `system_prompt` | the exact system prompt `text` + its `sha256` |
| `tools_schema` | the exact tool definitions sent to the model |
| `user_message` | the exact initial user message |
| `api_response` | one per API call: `step`, `latency_ms`, and the **raw response dump** — all content blocks (assistant text, thinking/reasoning where the provider returns it, tool calls), per-call usage (incl. reasoning-token details when reported), response id, served model, finish/stop reason, system fingerprint |
| `tool_execution` | `step`, `tool`, `tool_use_id`, parsed `arguments` (+ `raw_arguments` string on OpenAI-family), the **full untruncated `result`** (real names), `result_bytes` (in-memory frame footprint = the RQ4 cost axis), **`sent`** (the exact — masked and truncated — string the model received), `truncated` |
| `unmask` | if the final diagnosis named a pseudonym: the submitted (alias) form, the unmasked form used for scoring, and the alias→real mapping |
| `error` | captured exception `repr` if the diagnosis failed (transcript is still written) |

**Reconstructing what the model saw:** each `tool_execution` stores it directly in
`sent` — the pseudonymized, truncated string forwarded verbatim to the model — next to
the raw `result`, so a reviewer can compare evidence and model view side by side.
`result_bytes` counts the data the *tool* touched, which is larger than what was
forwarded; both are recorded.

## Anti-leakage (leakguard.py, `meta.mask_names`)

Injected-fault datasets leak their labels through names: run ids encode the fault
(`tt_slow_db_aggressive_steady_r1`) and injection containers are named after it
(`anomaly-cpu-stress`, `noisy-neighbor`). With `RCA_MASK_NAMES=1` (the default, and
the only setting valid for headline numbers):

- the model is given an opaque `incident-<hash>` alias, never the run id;
- fault-vocabulary identifiers in tool results are deterministically pseudonymized
  (`container-<hash>`); real service names (mysql, catalogue, …) are untouched — they
  are the answer space;
- the agent answers in alias space and the harness unmasks before scoring (the
  `unmask` event records the mapping).

Deliberately NOT masked (documented realism boundary): process signatures such as
`stress-ng` inside log/kernel evidence (seeing a co-tenant's processes is legitimate
SRE evidence — it reveals a synthetic workload, not which fault was injected), and the
incident window (the standard "an alert fired at [t0,t1]" RCA assumption, given
identically to every method including the baselines). The `submit_diagnosis` fault-type
enum is the closed answer space, identical for every incident, hence non-discriminative.

**Verification is automated:** `python audit_leakage.py <results.json…>` (or
`--transcripts <dir>`) rescans every model-visible input string for run ids,
fault-family tokens under any separator style, injection-container names and
ground-truth vocabulary — exit 1 on any hard hit. Run it after every sweep; ship the
PASS line with the artifact.

### `final`
`diagnosis` (the submitted `{root_cause_service, fault_type, evidence, confidence}`,
or `null`), `stop_reason` (`submitted` | `no_tool_calls` | `max_steps` | `error`),
`n_api_calls`, `n_tool_calls`, `tokens {in, out}`, `bytes_touched`, `wall_s`.

## Guarantees

1. **Ground-truth-free.** Transcripts contain no `ground_truth.json` content, no
   target service, no fault label — only the incident window (via tool outputs),
   which is the standard "an alert fired at [t0,t1]" RCA assumption. A reviewer can
   confirm no label leakage by inspecting the file.
2. **Secret-free.** Provider and model name only; never endpoints or API keys.
   `bundle_artifact.py` additionally scans every bundled byte against the local
   `.env` values and aborts on any hit.
3. **Complete on failure.** Errored diagnoses still write a transcript (with an
   `error` event), so the denominator of every reported rate is auditable.
4. **Tamper-evident when shared.** `bundle_artifact.py` packages results +
   transcripts + this schema with a `MANIFEST.sha256`; verify after unpacking with
   `sha256sum -c MANIFEST.sha256`.

## Sharing

```bash
python bundle_artifact.py results/agent_sweep*.json -o artifact_agent_sweep.tar.gz
```

## Caveat for older results

The 2026-08-11 sanity-gate results (`RESULTS-agent-sanitygate.md`) predate transcript
capture, so only their compact trajectories exist. The gate is cheap (23 incidents,
~12k output tokens total) — re-run it with capture enabled if its transcripts should
ship in the artifact.
