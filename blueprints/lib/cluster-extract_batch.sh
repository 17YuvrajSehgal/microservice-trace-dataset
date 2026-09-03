#!/bin/bash
# Stage L0 for every Sock Shop run of the two families under study.
set -uo pipefail
for R in noisy_neighbor_aggressive_steady_r1 noisy_neighbor_aggressive_steady_r2 \
         noisy_neighbor_aggressive_steady_r3 noisy_neighbor_subtle_steady_r1 \
         noisy_neighbor_subtle_steady_r2; do
  bash /scratch/yuvraj17/stratatrace/scripts/extract_l0.sh sockshop noisy_neighbor "$R"
done
for R in slow_db_aggressive_burst_r1 slow_db_aggressive_burst_r2 \
         slow_db_aggressive_steady_r1 slow_db_aggressive_steady_r2 \
         slow_db_aggressive_steady_r3 slow_db_subtle_steady_r1 slow_db_subtle_steady_r2; do
  bash /scratch/yuvraj17/stratatrace/scripts/extract_l0.sh sockshop slow_db "$R"
done
echo "== extract batch done $(date -u +%FT%TZ) =="
du -sh /scratch/yuvraj17/stratatrace/data/l0/sockshop/* | tail -20
