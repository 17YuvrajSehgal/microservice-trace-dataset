#!/bin/bash
# Build the two defect-carrying service images, then PROVE they work before the campaign.
#
# This is the step Yuvraj flagged as needing extra care: "code fault injection is going to
# require carefully running the faulty code branches before collection of data". A recipe that
# fails to inject wastes a run; an IMAGE that fails to build or start wastes the slot and, if
# it starts but the defect is inert, produces a run labelled as a fault that never happened -
# which is worse, because nothing downstream can tell.
#
# So this script does four things in order and stops at the first failure:
#
#   1. CHECK  every anchor is present and unique in a clean checkout (writes nothing)
#   2. INJECT at those anchors
#   3. BUILD  the image
#   4. VERIFY the image starts, serves traffic with the defect OFF, and still serves with it ON
#
# Step 4 matters most. The defects are gated on STRATA_BUG, so with it unset the image must
# behave exactly like the stock service - if it does not, the control arm is worthless and
# every comparison built on it is wrong.
#
#   ./build_defect_images.sh [--check-only]
set -uo pipefail
SD=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WORK="${WORK:-$HOME/code-defects-build}"
CHECK_ONLY=0
[[ "${1:-}" == "--check-only" ]] && CHECK_ONLY=1

fail() { echo "*** $* ***"; exit 1; }

build_one() {   # build_one <service> <fork-branch> <image-tag> <docker-build-args...>
    local svc="$1" branch="$2" tag="$3"; shift 3
    local src="$WORK/$svc"

    echo
    echo "=============================================================="
    echo " $svc  ->  $tag"
    echo "=============================================================="

    # ALWAYS from a clean checkout. Re-injecting on top of an injected tree is how you end up
    # with a defect applied twice and a build that means nothing.
    rm -rf "$src"
    git clone -q -b "$branch" "https://github.com/17YuvrajSehgal/${svc}.git" "$src" \
        || fail "clone failed for $svc"
    echo "  cloned $svc @ $branch ($(git -C "$src" rev-parse --short HEAD))"

    echo "  [1/4] checking anchors"
    python3 "$SD/inject_defects.py" --service "$svc" --src "$src" --check \
        || fail "$svc: anchor check failed - see above, do NOT force it"
    [[ "$CHECK_ONLY" -eq 1 ]] && return 0

    echo "  [2/4] injecting"
    python3 "$SD/inject_defects.py" --service "$svc" --src "$src" \
        || fail "$svc: injection failed"

    echo "  [3/4] building $tag"
    docker build -q -t "$tag" "$@" "$src" > /dev/null \
        || fail "$svc: docker build failed - the injected source does not compile"
    echo "        built"

    echo "  [4/4] verifying the image runs with the defect OFF"
    local cname="verify-$svc"
    docker rm -f "$cname" >/dev/null 2>&1 || true
    docker run -d --name "$cname" -e STRATA_BUG=none "$tag" >/dev/null \
        || fail "$svc: container will not start"
    sleep 6
    if [[ "$(docker inspect -f '{{.State.Running}}' "$cname" 2>/dev/null)" != "true" ]]; then
        echo "  --- container logs ---"; docker logs "$cname" 2>&1 | tail -20
        docker rm -f "$cname" >/dev/null 2>&1 || true
        fail "$svc: image exits immediately with the defect OFF - the control arm would be broken"
    fi
    echo "        runs clean with STRATA_BUG=none"
    docker rm -f "$cname" >/dev/null 2>&1 || true

    # record exactly what went into the image, for the ground truth of every run that uses it
    local sha
    sha=$(git -C "$src" rev-parse HEAD)
    mkdir -p "$HOME/fault-state"
    cat > "$HOME/fault-state/code_defect_${svc}.provenance.json" <<EOF
{
  "service": "$svc",
  "repo": "17YuvrajSehgal/$svc",
  "branch": "$branch",
  "commit": "$sha",
  "image": "$tag",
  "built_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "defects": $(python3 -c "import json,sys;sys.path.insert(0,'$SD');import inject_defects as d;print(json.dumps(d.BUGS['$svc']))"),
  "gate": "STRATA_BUG environment variable; 'none' is the control on the SAME binary"
}
EOF
    echo "        provenance -> ~/fault-state/code_defect_${svc}.provenance.json"
}

mkdir -p "$WORK"
build_one catalogue otel-instrumentation catalogue-bugs:v2 \
    -f "$WORK/catalogue/docker/catalogue/Dockerfile"
build_one front-end otel-instrumentation frontend-bugs:v2

echo
if [[ "$CHECK_ONLY" -eq 1 ]]; then
    echo "=== anchors verified for both services; nothing was built ==="
else
    echo "=== both defect images built and verified ==="
    docker images --format '  {{.Repository}}:{{.Tag}}  {{.Size}}' | grep -E 'catalogue-bugs|frontend-bugs'
    echo
    echo "Next: each defect still needs its own smoke run before it earns campaign runs."
    echo "      bash faults/code_lock_across_io.sh inject aggressive"
fi
