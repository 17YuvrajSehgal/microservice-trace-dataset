#!/usr/bin/env python3
"""Build the source tree the agent may read for a code_* run: the service at its recorded
commit, with ONLY that run's defect in it, written the way a developer would have written it.

WHY NOT THE TREE THE IMAGE WAS BUILT FROM. faults/code-defects/inject_defects.py puts all the
defects of a service into one binary behind a runtime gate, so one image serves every defect and
the control. That tree says `if strataBug() == "lock_across_io"` above a comment that names the
defect. Handing it to the agent hands over the answer. This script produces the tree a real
incident would have: no gate, no marker, one bug.

    python make_code_root.py --bug lock_across_io --src C:/workplace/catalogue --out <dir>
    python make_code_root.py --bug none --src C:/workplace/catalogue --out <dir>     # control

The gold location is printed, never written into --out.

Known gap: line numbers below the edit differ from the running binary's (the gate added ~45
lines to service.go / helpers/index.js), so a go-kit `caller=service.go:N` is off by that much.
logging.go and every other file are untouched and match exactly.
"""
from __future__ import annotations
import argparse, io, json, os, subprocess, sys, tarfile

GO_SELECT = "\terr := s.db.Select(&socks, query, args...)"
GO_IMPORT = 'import (\n\t"errors"\n\t"strings"\n\t"time"\n'
GO_CTOR = "func NewCatalogueService(db *sqlx.DB, logger log.Logger) Service {"
JS_REQ = ("  helpers.simpleHttpRequest = function(url, res, next) {\n"
          "    request.get(url, function(error, response, body) {")
JS_HEAD = '  var request = require("request");\n'

# bug -> (service, commit, file, gold function, [(anchor, replacement), ...])
BUGS = {
    "lock_across_io": ("catalogue", "0d18219", "service.go", "catalogueService.List", [
        (GO_IMPORT, 'import (\n\t"errors"\n\t"strings"\n\t"sync"\n\t"time"\n'),
        (GO_CTOR, "var listMu sync.Mutex\n\n" + GO_CTOR),
        (GO_SELECT, "\tlistMu.Lock()\n\tdefer listMu.Unlock()\n" + GO_SELECT)]),
    "n_plus_one": ("catalogue", "0d18219", "service.go", "catalogueService.List", [
        (GO_SELECT, GO_SELECT + "\n\tfor i := range socks {\n\t\tvar one Sock\n"
         "\t\t_ = s.db.Get(&one, \"SELECT * FROM sock WHERE sock_id = ?;\", socks[i].ID)\n\t}")]),
    "event_loop_block": ("front-end", "c11b5d9", "helpers/index.js", "helpers.simpleHttpRequest", [
        (JS_HEAD, JS_HEAD + "  var crypto = require('crypto');\n"),
        (JS_REQ, JS_REQ.replace("{\n", "{\n    var sig = crypto.pbkdf2Sync(url, 'salt', 120000, "
                                "64, 'sha512');\n", 1))]),
    "unbounded_cache": ("front-end", "c11b5d9", "helpers/index.js", "helpers.simpleHttpRequest", [
        (JS_HEAD, JS_HEAD + "  var requestLog = [];\n"),
        (JS_REQ, JS_REQ.replace("{\n", "{\n    requestLog.push({ url: url, at: Date.now(), "
                                "pad: Buffer.alloc(65536) });\n", 1))]),
    "serial_awaits": ("front-end", "c11b5d9", "helpers/index.js", "helpers.simpleHttpRequest", [
        (JS_REQ, JS_REQ.replace("{\n", "{\n    var until = Date.now() + 40;\n"
                                "    while (Date.now() < until) { }\n", 1))]),
}
SKIP = ("images/", "public/img/", "docs/", "test/e2e/", "vendor/")     # no code the agent needs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bug", required=True, choices=sorted(BUGS) + ["none"])
    ap.add_argument("--src", required=True, help="git checkout of the service")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    head = subprocess.check_output(["git", "-C", a.src, "rev-parse", "HEAD"], text=True).strip()
    spec = BUGS.get(a.bug)
    if spec and not head.startswith(spec[1]):
        sys.exit("refusing: %s is at %s, the run was built from %s" % (a.src, head[:7], spec[1]))
    os.makedirs(a.out, exist_ok=False)
    tar = subprocess.check_output(        # autocrlf off: a Windows checkout would archive CRLF
        ["git", "-C", a.src, "-c", "core.autocrlf=false", "archive", "HEAD"])
    with tarfile.open(fileobj=io.BytesIO(tar)) as tf:
        tf.extractall(a.out, members=[m for m in tf if not m.name.startswith(SKIP)],
                      filter="data")
    gold = {"bug": a.bug, "commit": head}
    if spec:
        _svc, _c, rel, func, edits = spec
        p = os.path.join(a.out, rel)
        s = open(p, encoding="utf-8", newline="").read()
        for anchor, repl in edits:
            if s.count(anchor) != 1:
                sys.exit("refusing: anchor not unique in %s: %r" % (rel, anchor[:50]))
            s = s.replace(anchor, repl)
        open(p, "w", encoding="utf-8", newline="").write(s)
        first = edits[-1][1].split("\n")[1 if a.bug != "n_plus_one" else -4].strip()
        line = next(i for i, l in enumerate(s.split("\n"), 1) if l.strip() == first)
        gold.update({"service": spec[0], "file": rel, "function": func, "line": line})
    assert "strata" not in open(os.path.join(a.out, spec[2] if spec else "README.md"),
                                encoding="utf-8", errors="replace").read().lower()
    print(json.dumps(gold))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
