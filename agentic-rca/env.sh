# Source this each Trillium session:   source agentic-rca/env.sh
# Order matters: python first (sets the compiler tree), then arrow (provides pyarrow via PYTHONPATH).
REPO="${REPO:-/scratch/yuvraj17/microservice-trace-dataset}"
module load python/3.11   >/dev/null 2>&1
module load arrow/19.0.1  >/dev/null 2>&1
source "$REPO/.venv/bin/activate"
export STRATATRACE_APP="${STRATATRACE_APP:-trainticket}"
export RUNS_ROOT="${RUNS_ROOT:-/scratch/yuvraj17/agentic-runs}"     # extracted working copies
export DATASET_ROOT="${DATASET_ROOT:-/project/def-naser2/yuvraj17/microservice-trace-dataset}"  # compressed archives
echo "agentic-rca env: $(python --version 2>&1) | pyarrow $(python -c 'import pyarrow;print(pyarrow.__version__)' 2>/dev/null) | app=$STRATATRACE_APP"
[ -z "${ANTHROPIC_API_KEY:-}" ] && echo "  (!) ANTHROPIC_API_KEY unset — needed only for the LLM agent (login node has internet); extraction/loader/degrade do not need it."
