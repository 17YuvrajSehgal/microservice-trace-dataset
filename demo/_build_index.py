#!/usr/bin/env python3
"""Build a demo index from one CTF directory. Run inside WSL (needs babeltrace2).

    BT2=babeltrace2 python3 demo/_build_index.py <ctf_dir> <out.tsv.gz> <out.lines.gz>

Thin wrapper over blueprints/lib/build_ctf_index.build with ctf_subdir='' so it decodes
the CTF directory directly, wherever it sits. Kept as a file (not an inline -c string) so
the demo server can invoke it over WSL without shell-quoting the code.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "blueprints", "lib"))
import build_ctf_index as B  # noqa: E402

ctf, out_tsv, out_lines = sys.argv[1], sys.argv[2], sys.argv[3]
r = B.build(ctf, out_tsv, ctf_subdir="", lines_path=out_lines)
if isinstance(r, dict) and r.get("error"):
    print("ERR:" + r["error"])
    sys.exit(1)
print("OK rows=%s events=%s" % (r.get("rows"), r.get("events_decoded")))
