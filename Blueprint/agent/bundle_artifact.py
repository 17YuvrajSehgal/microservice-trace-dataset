#!/usr/bin/env python3
"""Package results + full agent transcripts into ONE shareable, verifiable artifact.

    python bundle_artifact.py results/agent_sweep*.json -o artifact_agent_sweep.tar.gz

For each results JSON it pulls the transcripts referenced by the result rows (via
meta.transcripts_dir + each row's relative "transcript" path), adds TRANSCRIPTS.md
(the schema doc) and a MANIFEST.sha256, and writes a single tar.gz. Two safety rails:
  * refuses to bundle anything named .env
  * scans every bundled byte for the secret VALUES found in the local .env (if one
    exists) and aborts on a hit — API keys/endpoints must never ship with results.
Verify after unpacking:  sha256sum -c MANIFEST.sha256
"""
from __future__ import annotations
import argparse
import glob
import hashlib
import io
import json
import os
import sys
import tarfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_SECRET_KEY = ("key", "secret", "token", "password", "credential", "endpoint")


def _env_secrets() -> list[bytes]:
    """Values (len>=8) of secret-bearing .env keys, used as a deny-list scan over bundled
    bytes. Only keys that look credential-like count — benign config values (e.g.
    STRATATRACE_APP=trainticket) legitimately appear in transcript metadata."""
    out = []
    for cand in (os.path.join(HERE, "..", ".env"), os.path.join(HERE, ".env"), ".env"):
        if os.path.isfile(cand):
            for line in open(cand, encoding="utf-8", errors="ignore"):
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    v = v.strip().strip("'\"")
                    if len(v) >= 8 and any(s in k.lower() for s in _SECRET_KEY):
                        out.append(v.encode())
            break
    return out


def collect(results_paths: list[str]) -> dict[str, bytes]:
    """arcname -> file bytes for every results file + every referenced transcript."""
    files: dict[str, bytes] = {}
    missing = 0
    for rp in results_paths:
        doc = json.load(open(rp, encoding="utf-8"))
        # include the parent dir: files named alike across condition dirs must not collide
        parent = os.path.basename(os.path.dirname(os.path.abspath(rp)))
        stem = f"{parent}_{os.path.splitext(os.path.basename(rp))[0]}"
        files[f"results/{parent}/{os.path.basename(rp)}"] = open(rp, "rb").read()
        tdir = (doc.get("meta") or {}).get("transcripts_dir")
        for row in doc.get("results", []):
            rel = row.get("transcript")
            if not rel or not tdir:
                continue
            src = os.path.join(tdir, rel)
            if not os.path.isfile(src):
                missing += 1
                continue
            files[f"transcripts/{stem}/{rel.replace(os.sep, '/')}"] = open(src, "rb").read()
    if missing:
        print(f"WARNING: {missing} transcripts referenced by results are missing on disk", file=sys.stderr)
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="+", help="results JSON file(s) or globs from evaluate.py")
    ap.add_argument("-o", "--out", required=True, help="output .tar.gz path")
    a = ap.parse_args()
    paths = sorted({p for pat in a.results for p in glob.glob(pat)})
    if not paths:
        raise SystemExit("no results files matched")
    files = collect(paths)
    schema = os.path.join(HERE, "TRANSCRIPTS.md")
    if os.path.isfile(schema):
        files["TRANSCRIPTS.md"] = open(schema, "rb").read()

    secrets = _env_secrets()
    for name, data in files.items():
        if os.path.basename(name) == ".env":
            raise SystemExit(f"refusing to bundle {name}")
        for s in secrets:
            if s in data:
                raise SystemExit(f"SECRET LEAK: a .env value appears in {name} — aborting")

    manifest = "".join(f"{_sha256(data)}  {name}\n" for name, data in sorted(files.items()))
    files["MANIFEST.sha256"] = manifest.encode()

    with tarfile.open(a.out, "w:gz") as tar:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = int(time.time())
            tar.addfile(info, io.BytesIO(data))
    n_tr = sum(1 for n in files if n.startswith("transcripts/"))
    print(f"wrote {a.out}: {len(paths)} results file(s), {n_tr} transcripts, "
          f"{sum(len(d) for d in files.values()) / 1e6:.1f} MB uncompressed")


if __name__ == "__main__":
    main()
