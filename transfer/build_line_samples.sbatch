#!/bin/bash
#SBATCH --job-name=ctflines
#SBATCH --nodes=1
#SBATCH --time=03:00:00
#SBATCH --output=/scratch/yuvraj17/stratatrace/slurm-logs/ctflines_%j.out
#
# Build the raw-line sample that makes ctf_lines a file read instead of a whole-trace decode.
#
# WHY. Measured from live transcripts on 22-09: ctf_lines is 80% of an agent run's wall clock -
# 378 s of a 500 s run - because babeltrace cannot seek and re-decodes the trace from the start
# to reach any range. Every other tool answers in about 2 s off the count index, and the Azure
# API accounts for 27 s. So the run is not API-bound and not parallelism-bound: it is bound by
# decoding the same 385 million events over and over to return 40 lines.
#
# The index pass already decodes every event once, so keeping one line per (bucket, event)
# costs nothing extra here. Expected effect: a run drops from about 9 minutes to about 2.
#
# STAGED, not written in place. An agent matrix may be running on the login node, and dropping
# a line sample beside the live index would change ctf_lines under it mid-experiment - half the
# cells with a different cost and a different sample. Install with the mv step below only when
# nothing is in flight.
#
#   sbatch transfer/build_line_samples.sbatch [todo-file]

set -u
S=/scratch/yuvraj17/stratatrace
TODO="${1:-$S/results/lines_todo.txt}"
STAGE="$S/dataset/index-staging"
PAR="${PAR:-34}"

mkdir -p "$STAGE"
echo "node $(hostname)   start $(date -u +%H:%M:%S)"
echo "todo: $(wc -l < "$TODO") runs   parallel: $PAR   staging: $STAGE"
"$S/tools/bt21.sh" --version | head -1

# --with-lines writes BOTH the count table and the line sample. The count tables here are
# throwaway duplicates of the live ones; only the .lines.gz files get installed.
grep -v '^[[:space:]]*$' "$TODO" | xargs -P "$PAR" -I{} \
  "$HOME/q2venv/bin/python" -u "$S/repo/blueprints/lib/build_ctf_index.py" \
  --out-root "$STAGE" --with-lines --force {}
rc=$?

echo "end $(date -u +%H:%M:%S)  rc=$rc"
echo "line samples built: $(ls "$STAGE"/*.lines.gz 2>/dev/null | wc -l)"
du -sh "$STAGE" 2>/dev/null
echo
echo "TO INSTALL, once no matrix is running:"
echo "  mv $STAGE/*.lines.gz $S/dataset/index/"
exit $rc
