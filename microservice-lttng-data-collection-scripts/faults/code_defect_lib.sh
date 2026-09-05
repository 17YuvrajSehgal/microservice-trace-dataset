#!/bin/bash
# Shared implementation for the code-defect recipes.
#
# Every defect is gated at runtime on STRATA_BUG inside an image built by
# code-defects/build_defect_images.sh. Injecting a defect therefore means recreating one
# container with a different environment variable, and cleaning up means putting it back to
# "none" - the control - on the SAME binary.
#
# THE POINT OF THE FLAG. A patched image is not the stock image: different build, different
# layer, possibly a different compiler pass. If the control were the stock service, every
# comparison would measure the rebuild as well as the defect. With the flag, control and fault
# are the same bytes and the only difference is the code path taken.
#
# A recipe sources this file, sets DEFECT_* and calls code_defect_dispatch "$@".

code_defect_require_image() {
    if ! docker image inspect "$DEFECT_IMAGE" >/dev/null 2>&1; then
        echo "*** $DEFECT_IMAGE has not been built."
        echo "*** Run: bash faults/code-defects/build_defect_images.sh"
        exit 1
    fi
}

# Recreate the service container from the defect image with STRATA_BUG set. Compose owns the
# original container, so we take a full copy of its configuration first and put it back on
# cleanup - anything less leaves the stack subtly different for every later run.
code_defect_apply() {   # code_defect_apply <bug-name-or-none>
    local bug="$1"
    local cname; cname="$(resolve_container "$DEFECT_SERVICE")"

    docker inspect "$cname" >/dev/null 2>&1 || { echo "no such container: $cname"; exit 1; }

    # Preserve the network, aliases and env so the recreated container is a drop-in.
    local net alias_args env_args
    net=$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' "$cname" | head -1)
    alias_args=$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{range $v.Aliases}}--network-alias {{.}} {{end}}{{end}}' "$cname")
    env_args=$(docker inspect -f '{{range .Config.Env}}--env {{.}} {{end}}' "$cname" \
               | tr ' ' '\n' | grep -v '^--env STRATA_BUG=' | tr '\n' ' ')

    docker rm -f "$cname" >/dev/null 2>&1 || true
    # shellcheck disable=SC2086
    docker run -d --name "$cname" --network "$net" $alias_args $env_args \
        --env "STRATA_BUG=$bug" ${DEFECT_RUN_ARGS:-} "$DEFECT_IMAGE" ${DEFECT_CMD:-} >/dev/null \
        || { echo "failed to start $cname from $DEFECT_IMAGE"; exit 1; }

    # A defect that never actually ran produces a run labelled as a fault that did not happen.
    sleep 5
    if [[ "$(docker inspect -f '{{.State.Running}}' "$cname" 2>/dev/null)" != "true" ]]; then
        echo "[$FAULT_NAME] CONTAINER DID NOT STAY UP with STRATA_BUG=$bug - logs:"
        docker logs "$cname" 2>&1 | tail -20
        exit 1
    fi
    echo "[$FAULT_NAME] $cname running from $DEFECT_IMAGE with STRATA_BUG=$bug"
}

code_defect_dispatch() {
    case "${1:-}" in
      inject)
        code_defect_require_image
        local intensity="${2:-aggressive}"
        code_defect_apply "$DEFECT_BUG"
        local prov="$HOME/fault-state/code_defect_${DEFECT_SERVICE}.provenance.json"
        local commit="unknown"
        [[ -f "$prov" ]] && commit=$(python3 -c "import json;print(json.load(open('$prov'))['commit'])" 2>/dev/null || echo unknown)
        gt_begin "$intensity" "{\"kind\": \"code_defect\", \"service\": \"$DEFECT_SERVICE\", \"image\": \"$DEFECT_IMAGE\", \"bug\": \"$DEFECT_BUG\", \"commit\": \"$commit\", \"mechanism\": \"$DEFECT_MECHANISM\", \"correct_fix\": \"$DEFECT_FIX\", \"pairs_with\": \"$DEFECT_PAIRS_WITH\", \"control\": \"same image with STRATA_BUG=none\"}"
        ;;
      control)
        # The paired healthy run: same image, defect off. Not a normal run - a control run.
        code_defect_require_image
        code_defect_apply none
        echo "[$FAULT_NAME] control armed: identical binary, defect disabled"
        ;;
      cleanup)
        code_defect_apply none
        gt_end
        ;;
      status)
        local cname; cname="$(resolve_container "$DEFECT_SERVICE")"
        docker inspect -f '{{.Name}} image={{.Config.Image}} STRATA_BUG={{range .Config.Env}}{{if eq (slice . 0 (min 11 (len .))) "STRATA_BUG="}}{{slice . 11}}{{end}}{{end}}' "$cname" 2>/dev/null \
            || docker ps --filter "name=$cname" --format '{{.Names}} {{.Image}} {{.Status}}'
        ;;
      *) echo "usage: $0 inject [subtle|aggressive] | control | cleanup | status"; exit 1 ;;
    esac
}
