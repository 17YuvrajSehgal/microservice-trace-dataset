#!/bin/bash
# build_all.sh - build every v4 program into v4/build/<problem>/<language>/.
#   build_all.sh [problem ...]      (default: all problems)
set -uo pipefail
V4="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export GOCACHE="${GOCACHE:-$HOME/.cache/go-build}" GO111MODULE=off
fail=0
for p in ${@:-$(ls "$V4/problems")}; do
    SHORT=$(sed -n 's/^SHORT=//p' "$V4/problems/$p/problem.sh")
    for lang in c go java python node; do
        src="$V4/problems/$p/$lang"
        [[ -d "$src" ]] || continue
        out="$V4/build/$p/$lang"
        rm -rf "$out"; mkdir -p "$out"
        case "$lang" in
            c)      gcc -O2 -pthread -o "$out/${SHORT}_c" "$src/main.c" ;;
            go)     (cd "$src" && go build -o "$out/${SHORT}_go" main.go) ;;
            java)   javac -d "$out" "$src/Main.java" ;;
            python) cp "$src/main.py" "$out/" && python3 -m py_compile "$out/main.py" ;;
            node)   cp "$src/main.js" "$out/" && node --check "$out/main.js" ;;
        esac
        if [[ $? -eq 0 ]]; then echo "built $p/$lang"; else echo "FAILED $p/$lang"; fail=1; fi
    done
done
exit $fail
