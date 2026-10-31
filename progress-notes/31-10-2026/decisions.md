# 2026-10-31 — ran the Sock Shop svc_mem_cap eval (new memcg runs, direct OpenAI)

Continues the 29-30 Oct memcg re-collection (see `progress-notes/29-10-2026/decisions.md`).

## New OpenAI key → direct `openai` provider (was OpenRouter)
User supplied a direct OpenAI key. Transferred to Trillium **without reading it**:
`grep '^OPENAI_API_KEY=' .env | ssh trillium 'umask 077; cat > ~/openai_key.env'` (value never
displayed; the run script sources it, so it never hits a command line). Three direct-OpenAI
incompatibilities the prior OpenRouter path had hidden — all fixed:
1. **CRLF in the key.** The Windows `.env` has CRLF, so the transferred key carried a trailing `\r`
   → SDK sent `Bearer …\r` → `APIConnectionError` (really `LocalProtocolError: illegal header`).
   `sed -i 's/\r$//'`. **The error message printed the full key** (SDK echoed the rejected header) —
   flagged to the user to rotate if they want; it only hit this session's output, no file/commit.
2. **`reasoning_effort=none` required.** gpt-5.x luna via chat.completions rejects the call unless
   reasoning_effort is pinned (OpenAI exposes reasoning only via the Responses API). Fixed in
   `config.py` scoped to `PROVIDER=openai`, env-tunable `RCA_REASONING_EFFORT` (committed). Means
   reasoning is OFF for these runs — consistent with the OpenRouter chat path.
3. **Model id.** `gpt-6-luna` resolves as an alias on direct OpenAI (dashboard lists `gpt-5.6-luna`);
   both work, same underlying model as all prior results.
Also found + fixed a stale-cache trap: `eval_matrix.discover()` uses recursive `os.walk`, so
`--runs-root .../sockshop` would pull in the parked `_superseded_no_memcg_20261029/` runs — point it
at `.../sockshop/svc_mem_cap`. And 7 stale `result.json` cells (27 Oct, no-memcg) were moved aside
first, else the resumable harness skips re-running.

## Result — svc_mem_cap × Sock Shop (8 runs, matched arm, by hand)
**3/8 DETECTED + 2 PARTIAL + 3 MISS.** subtle 2/3 > aggressive 1/5 clean.
- Localization graded by **mechanism, not nsmap** (its CPU correlation mislabelled carts as
  front-end, ratios to 16×). The in-window memcg reclaim is `java`/pid_ns 4026532540 = carts (299
  events r1, 236 subtle_r2; stable across 29-30 Oct — stack never restarted). The agent reports the
  raw pid_ns; naming 4026532540 = correct carts localization.
- Honest reading: the fix works at the eval level (signal present in all 8, agent found the reclaim
  in carts every time). Lower than agentic 44/44 for two structural reasons — a 13-container app
  also needs localization (failed twice), and the aggressive 160m cap's violent teardown reads as
  "workload teardown" → `other` (twice). Subtle (300m) reads cleaner. Misses are over-conservatism,
  never hallucination. Single-run preliminary; N-seed after freeze is the citable number.
- Cost $0.97 (9.3M in + 75k out, ~13 min, jobs=6).

## Docs updated
`RESULTS.md` (§svc_mem_cap replaces the "not evaluable" section + Sock Shop table row + next-steps),
new `results/sockshop/JUDGMENTS-svc_mem_cap.md`, `HANDOFF-RERUN.md` (A0 done + direct-OpenAI
lessons), `RUNS-TRACKER.md`, `DATASET-v2-INVENTORY.md`.

## Still open
Train Ticket svc_mem_cap (same memcg gap, not re-collected); N-seed freeze run; control arm
(`--arm none`); microservice normal-run controls.
