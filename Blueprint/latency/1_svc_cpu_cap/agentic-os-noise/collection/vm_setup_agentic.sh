#!/bin/bash
# One-time VM setup for the agentic OS-noise experiments.
# LTTng 2.15 kernel tracing only - no Docker, no Sock Shop.
# After this: install + sign in the agent (claude.ai/install.sh or npm),
# then verify with:  claude -p 'Reply with exactly: hello'
set -x

sudo add-apt-repository -y ppa:lttng/stable-2.15
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    lttng-tools lttng-modules-dkms babeltrace2 git python3-pip

# dkms drops .ko files without refreshing the module index (vm_bootstrap.sh
# lesson, 2026-09-04) - depmod before the first modprobe.
sudo depmod -a
sudo modprobe lttng-tracer || { echo "FATAL: lttng-tracer will not load on $(uname -r)"; exit 1; }

# Prove tracing end-to-end: record 3 s and read it back.
# (`lttng list --kernel` line counts are unreliable on kernel 7.x.)
sudo lttng create smoke --output=/tmp/smoke
sudo lttng enable-event -k sched_switch
sudo lttng start; sleep 3; sudo lttng stop; sudo lttng destroy smoke
n=$(sudo babeltrace2 /tmp/smoke 2>/dev/null | wc -l)
sudo rm -rf /tmp/smoke
[ "$n" -gt 100 ] || { echo "FATAL: smoke trace empty"; exit 1; }
echo "=== SETUP DONE (smoke trace: $n events) ==="
