#!/bin/bash
# Package one collected run into a self-describing bundle, ready to move to Trillium.
#
# WHY THIS EXISTS
# ---------------
# v1 runs arrived on the cluster as bare directories. Working out what one contained meant
# opening it, and there was no way to tell a good run from one that had silently lost events -
# because nothing recorded that. This writes a MANIFEST.json and SHA256SUMS beside every run so
# a bundle states what it is, whether it is trustworthy, and whether it arrived intact.
#
#   ./package_run.sh <run_dir> [--tar]
#
# --tar also produces <run_dir>.tar (streams already gzipped inside, so no double compression).
set -uo pipefail
RUN_DIR="${1:?usage: package_run.sh <run_dir> [--tar]}"
TAR=0
[[ "${2:-}" == "--tar" ]] && TAR=1

[[ -d "$RUN_DIR" ]] || { echo "no such run: $RUN_DIR"; exit 1; }
RUN_ID=$(basename "$RUN_DIR")

# Compress the CTF streams if the campaign driver has not already. metadata and index stay
# uncompressed so a reader can open the trace.
#
# MEASURED 5 Sept on a real Train Ticket bundle, not estimated. The comment used to say ~3-4x:
#
#   raw bundle          34.9 GB for a 165 s run   (49 containers, 40 of them JVMs)
#   gzip -1 ratio       8.26x                     (better than the 3-4x assumed here)
#   gzip -1 rate        120 MB/s single-threaded
#
# 8.26x is what makes the campaign fit at all: a 240 s Train Ticket run is ~51 GB raw and
# ~6 GB packed, so 134 of them come to roughly 820 GB on a 1 TB archive.
#
# PIGZ, NOT GZIP. At 120 MB/s a single run takes ~7 minutes to compress, and 134 runs is nearly
# 16 hours of the campaign spent waiting on one core out of sixteen. pigz does the same work in
# parallel for the same bytes - gzip format, same ratio, readable by everything downstream.
GZIP_BIN="$(command -v pigz || command -v gzip)"
GZIP_ARGS="-1"
[[ "$GZIP_BIN" == *pigz ]] && GZIP_ARGS="-1 -p $(nproc)"
if [[ -d "$RUN_DIR/kernel/kernel" ]]; then
    echo "[pack] compressing CTF streams with $(basename "$GZIP_BIN") $GZIP_ARGS"
    # shellcheck disable=SC2086
    "$GZIP_BIN" $GZIP_ARGS -q "$RUN_DIR"/kernel/kernel/channel0_* 2>/dev/null || true
fi

python3 - "$RUN_DIR" "$RUN_ID" <<'PY'
import hashlib, json, os, re, sys

run_dir, run_id = sys.argv[1], sys.argv[2]


def sha256(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(buf), b""):
            h.update(chunk)
    return h.hexdigest()


def read(rel):
    p = os.path.join(run_dir, rel)
    try:
        return open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


def load_json(rel):
    p = os.path.join(run_dir, rel)
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:                                                  # noqa: BLE001
        return None


# --- what this run IS -------------------------------------------------------------------
# run ids look like  <family>_<intensity>_<workload>_r<n>  (tt_ prefixed on the second app)
m = re.match(r"^(tt_)?(?P<fam>.+?)_(?P<intensity>aggressive|subtle|none)"
             r"_(?P<workload>steady|burst)_r(?P<rep>\d+)$", run_id)
ident = {"run_id": run_id,
         "app": "trainticket" if run_id.startswith("tt_") else "sockshop",
         "family": m.group("fam") if m else None,
         "intensity": m.group("intensity") if m else None,
         "workload": m.group("workload") if m else None,
         "repeat": int(m.group("rep")) if m else None}

# --- is it trustworthy? -----------------------------------------------------------------
loss = load_json("meta/event_loss.json")
verif = load_json("verification.json")
enabled = read("meta/lttng_enabled_kernel.txt")

quality = {
    # THE check v1 could not make: did LTTng drop anything?
    "event_loss": loss or {"clean": None, "note": "not recorded - pre-v2 run"},
    # did the injected fault actually move its target metric?
    "verification": (verif or {}).get("verification_status", "n/a"),
    # the v2 additions, so a reader can tell which profile produced this run
    # v1 produced 50 Sock Shop runs with a verification verdict and NOT ONE image, because
    # matplotlib was missing and the failure was silent. The image is the human-readable proof
    # that a fault took effect and it cannot be regenerated later - the Prometheus data behind
    # it is not retained. So a missing one is reported per run, not found a month afterwards.
    "has_verification_image": os.path.exists(os.path.join(run_dir, "verification.png")),
    "has_namespace_context": bool(re.search(r"\b(cgroup_ns|pid_ns|net_ns)\b", enabled)),
    "has_memory_tracepoints": bool(re.search(r"\bvmscan_|\bkmem_", enabled)),
    "enabled_events_recorded": bool(enabled),
}
usable = (quality["event_loss"].get("clean") is not False
          and quality["verification"] in ("confirmed", "n/a", "borderline"))
quality["usable"] = usable
quality["why_not"] = None if usable else (
    "events were discarded" if quality["event_loss"].get("clean") is False
    else f"injection {quality['verification']}")

# --- what is in the box -----------------------------------------------------------------
parts, files, total = {}, [], 0
for root, _dirs, names in os.walk(run_dir):
    for n in names:
        if n in ("MANIFEST.json", "SHA256SUMS"):
            continue
        full = os.path.join(root, n)
        rel = os.path.relpath(full, run_dir).replace("\\", "/")
        try:
            size = os.path.getsize(full)
        except OSError:
            continue
        total += size
        top = rel.split("/")[0]
        p = parts.setdefault(top, {"files": 0, "bytes": 0})
        p["files"] += 1
        p["bytes"] += size
        files.append((rel, size, full))

# Checksums on everything would take minutes on a 14 GB trace. Checksum the small, decisive
# files in full, and record size only for the bulk streams - which the tar/rsync layer already
# protects. What matters is that ground truth and metadata cannot drift unnoticed.
CHECKSUM_ALWAYS = ("ground_truth.json", "verification.json", "MANIFEST",
                   "meta/", "otlp/", "logs/", "metrics/")
sums = {}
for rel, size, full in sorted(files):
    if rel.startswith(CHECKSUM_ALWAYS) or size < 8 * 1024 * 1024:
        sums[rel] = sha256(full)

manifest = {
    "schema": "stratatrace-run/2",
    "identity": ident,
    "quality": quality,
    "contents": {"total_bytes": total, "total_files": len(files),
                 "by_part": dict(sorted(parts.items()))},
    "checksums": {"algorithm": "sha256", "covered_files": len(sums),
                  "note": "small and decisive files only; bulk CTF streams are size-checked"},
}
json.dump(manifest, open(os.path.join(run_dir, "MANIFEST.json"), "w"), indent=2)
with open(os.path.join(run_dir, "SHA256SUMS"), "w", encoding="utf-8") as f:
    for rel, digest in sorted(sums.items()):
        f.write(f"{digest}  {rel}\n")

gb = total / 1e9
flag = "" if usable else f"   ** NOT USABLE: {quality['why_not']} **"
# `loss={clean}` printed True when the trace was CLEAN. Read literally that says the opposite of
# what it means, and over 300 runs the one line an operator actually scans must not be
# ambiguous - especially when the dangerous value (loss=False) was the one that looked fine.
_clean = quality["event_loss"].get("clean")
_trace = "clean" if _clean is True else ("LOST EVENTS" if _clean is False else "unrecorded")
print(f"[pack] {run_id:44s} {gb:6.2f} GB  "
      f"trace={_trace}  "
      f"verif={quality['verification']}  "
      f"ns={quality['has_namespace_context']}  mem={quality['has_memory_tracepoints']}  "
      f"img={quality['has_verification_image']}{flag}")
if not quality["has_verification_image"]:
    print("       ^ NO verification.png - is matplotlib installed on this VM?")
PY

if [[ "$TAR" -eq 1 ]]; then
    tar -cf "${RUN_DIR}.tar" -C "$(dirname "$RUN_DIR")" "$RUN_ID"
    echo "[pack] wrote ${RUN_DIR}.tar"
fi
