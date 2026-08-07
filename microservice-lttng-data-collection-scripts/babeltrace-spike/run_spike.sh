#!/bin/bash
# Spike: prove Babeltrace2 ingests non-LTTng data (§4.2 gating question).
# Run on the VM. Read-only on ~/traces. See SPIKE.md.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== 1. Babeltrace2 present + its plugins (source/filter/sink components) ==="
babeltrace2 --version
babeltrace2 list-plugins 2>/dev/null | grep -E 'Plugin|ctf|text|utils|lttng' | head -30

echo
echo "=== 2. BUILT-IN PROOF: source.text.dmesg parses a plain-text (non-CTF) log ==="
DMESG=/tmp/spike_dmesg.txt
{ dmesg 2>/dev/null || sudo dmesg 2>/dev/null; } > "$DMESG"
echo "dmesg lines captured: $(wc -l < "$DMESG")"
echo "--- first bt2 events decoded from that plain text: ---"
babeltrace2 "$DMESG" --component=source.text.dmesg 2>/dev/null | head -5 \
  || babeltrace2 --component=source.text.dmesg --params="path=\"$DMESG\"" 2>/dev/null | head -5
echo "[ if events printed above, Babeltrace2 ingests non-LTTng text -> gating question ANSWERED ]"

echo
echo "=== 3. CUSTOM PROOF: our Sock Shop app logs as bt2 events ==="
echo "--- 3a. offline parse self-test (no bt2 needed) ---"
python3 "$DIR/applog_source.py" --selftest
LOG=$(ls "$HOME"/traces/*/*/logs/docker-compose_catalogue_1.log 2>/dev/null | head -1)
echo "--- 3b. run the source plugin over a real dataset log: $LOG ---"
if [ -n "$LOG" ]; then
  babeltrace2 --plugin-path="$DIR" \
    --component=source.sockshop.applog --params="path=\"$LOG\"" 2>&1 | head -8 \
    || echo "[ plugin needs the python3-bt2 bindings / a minor API tweak — see SPIKE.md ]"
else
  echo "[ no catalogue log found under ~/traces — run a collection first ]"
fi
echo
echo "=== spike done ==="
