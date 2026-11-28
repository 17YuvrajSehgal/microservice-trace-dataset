# common.sh - sourced by every problem.sh through collect_v4.sh: how each language's program is
# started and what the kernel calls it (procname). Binaries are named <short>_c / <short>_go so the
# trace shows which problem program it is; the kernel cuts names at 15 characters.
program_cmd() {
    case "$1" in
        c)      echo "./${SHORT}_c" ;;
        go)     echo "./${SHORT}_go" ;;
        java)   echo "java -Xss512k -cp . Main" ;;
        python) echo "python3 -u main.py" ;;
        node)   echo "node main.js" ;;
    esac
}
program_comm() {
    case "$1" in
        c)      echo "${SHORT}_c" | cut -c1-15 ;;
        go)     echo "${SHORT}_go" | cut -c1-15 ;;
        java)   echo java ;;
        python) echo python3 ;;
        node)   echo node ;;
    esac
}
# Wait until the program has written N "role tid" lines to $V4_TIDS (priority inversion uses it).
wait_tids() {
    local n=$1 i
    for i in $(seq 1 50); do [[ -f "$V4_TIDS" ]] && [[ $(wc -l < "$V4_TIDS") -ge $n ]] && return 0; sleep 0.2; done
    echo "[v4] the program did not report its $n threads"; return 1
}
