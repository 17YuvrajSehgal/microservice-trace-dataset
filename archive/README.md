# archive/

Kept-but-inactive material, moved here in the 2026-08-08 repo reorg. **Nothing here is deleted** —
it's out of the active tree but intact and reversible (git tracked the moves as renames, so history
is preserved).

| Path | What | Why archived |
|---|---|---|
| `lmat/microservice/` | LMAT preprocessing/training/eval pipeline (NpzDataset, preprocess_*, train_sockshop, run_root_cause_eval, validate_*) | The JSS-paper (LMAT SockShop) modeling code. No current agentic/dataset work imports it. |
| `lmat/models/`, `lmat/dataset/` | Vendored model + dataset packages (from adaptive_tracer @405e49e) used *only* by `lmat/microservice/` | Vendored authoritative copies (see VENDORED.md in each); kept for the JSS revision. |
| `lmat/docs/` | LMAT/JSS docs: `lmat_inference_evaluation.md`, `end_to_end_lmat_experiment_reference.md`, `reviewer_comments.txt`, `review1-answer.md` | JSS review-era documents. |
| `progress-snapshots/` | Dated standalone progress/update files (`daily-update-2026-08-03`, `progress-01-08-2026`, `update-29-07-2026`, `todolist-31-07-2026`) | Superseded by the live `progress-notes/` daily log. |

To bring anything back, `git mv archive/<...> <dest>`.
