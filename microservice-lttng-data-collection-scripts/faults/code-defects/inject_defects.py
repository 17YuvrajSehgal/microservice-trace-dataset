#!/usr/bin/env python3
"""Insert the code defects into a clean checkout of a service, at verified anchors.

WHY NOT .patch FILES
--------------------
A diff carries line numbers and context, so it breaks the moment upstream shifts a line and it
breaks in a way that is easy to force through with --fuzz. This inserts at EXACT anchor
strings and refuses to continue if an anchor is missing or ambiguous. On a campaign we cannot
repeat, a build that quietly applied half a patch is far worse than one that stopped.

WHY ONE IMAGE PER SERVICE AND NOT ONE PER BUG
---------------------------------------------
Every defect is gated at runtime on the STRATA_BUG environment variable. So a service builds
ONCE and the same binary serves every defect and the control.

That matters for correctness, not just convenience. A patched image is not the stock image -
different build date, different layer, possibly a different compiler pass. If the control were
the stock image, the comparison would measure the rebuild as well as the defect. With a flag,
the control is `STRATA_BUG=none` on the identical binary, so the only difference is the code
path taken.

    python3 inject_defects.py --service catalogue --src ~/catalogue [--check]

--check verifies every anchor is present and unique WITHOUT writing, which is what the build
script runs first so a bad anchor is caught before any image is built.
"""
from __future__ import annotations
import argparse, os, sys

# ---------------------------------------------------------------------------------------
# Each edit: (file, anchor, replacement, note). The anchor must appear EXACTLY ONCE.
# ---------------------------------------------------------------------------------------

CATALOGUE = [
    (
        "service.go",
        'import (\n\t"errors"\n\t"strings"\n\t"time"\n',
        'import (\n\t"errors"\n\t"os"\n\t"strings"\n\t"sync"\n\t"time"\n',
        "add os and sync for the defect gate",
    ),
    (
        "service.go",
        "func NewCatalogueService(db *sqlx.DB, logger log.Logger) Service {",
        # A package-level mutex plus the runtime gate. Nothing here changes behaviour unless
        # STRATA_BUG names a defect, so the control path is the original code.
        "// --- StrataTrace code-defect injection -------------------------------------------\n"
        "// Behaviour is selected at RUNTIME by STRATA_BUG so one build serves every defect and\n"
        "// the control. With STRATA_BUG unset or \"none\" this file behaves exactly as upstream.\n"
        "var strataMu sync.Mutex\n"
        "\n"
        "func strataBug() string { return os.Getenv(\"STRATA_BUG\") }\n"
        "\n"
        "func NewCatalogueService(db *sqlx.DB, logger log.Logger) Service {",
        "declare the defect gate",
    ),
    (
        "service.go",
        "\terr := s.db.Select(&socks, query, args...)",
        # DEFECT 1: the lock is held across the database round trip, so every List request
        # serialises behind one mutex. The single most common real concurrency bug in service
        # code, and the honest counterpart to the synthetic lock_contention recipe.
        "\tif strataBug() == \"lock_across_io\" {\n"
        "\t\tstrataMu.Lock()\n"
        "\t\tdefer strataMu.Unlock()\n"
        "\t}\n"
        "\terr := s.db.Select(&socks, query, args...)\n"
        "\tif strataBug() == \"n_plus_one\" {\n"
        # DEFECT 2: one extra query per row. Database work grows with result size, so it looks
        # like a slow datastore while the datastore is perfectly healthy.
        "\t\tfor i := range socks {\n"
        "\t\t\tvar one Sock\n"
        "\t\t\t_ = s.db.Get(&one, \"SELECT * FROM sock WHERE sock_id = ?;\", socks[i].ID)\n"
        "\t\t}\n"
        "\t}",
        "lock_across_io and n_plus_one, both on the List query path",
    ),
]

FRONTEND = [
    (
        "helpers/index.js",
        "(function (){\n  'use strict';\n",
        # helpers is required by every API module, so gating here covers the whole surface
        # without touching each route.
        "(function (){\n  'use strict';\n"
        "\n"
        "  // --- StrataTrace code-defect injection ---------------------------------------\n"
        "  // Selected at RUNTIME by STRATA_BUG so one build serves every defect and the\n"
        "  // control. Unset or \"none\" behaves exactly as upstream.\n"
        "  var strataBug = function () { return process.env.STRATA_BUG || 'none'; };\n"
        "  var strataCache = [];   // deliberately unbounded, for the cache defect\n"
        "  var crypto = require('crypto');\n",
        "add the defect gate to the shared helper module",
    ),
    (
        "helpers/index.js",
        # The real signature, read off the checkout: an assignment onto `helpers`, not an
        # object-literal member. Guessing it cost one anchor-check cycle and zero builds,
        # which is exactly what checking anchors before building is for.
        "  helpers.simpleHttpRequest = function(url, res, next) {\n"
        "    request.get(url, function(error, response, body) {",
        "  helpers.simpleHttpRequest = function(url, res, next) {\n"
        "    var _bug = strataBug();\n"
        "    if (_bug === 'event_loop_block') {\n"
        # DEFECT 3: synchronous CPU work inside a request handler. Node has ONE thread, so the
        # WHOLE service stops - including requests that never touch this path. Nothing else in
        # the dataset produces that shape.
        "      crypto.pbkdf2Sync('strata', 'salt', 120000, 64, 'sha512');\n"
        "    }\n"
        "    if (_bug === 'unbounded_cache') {\n"
        # DEFECT 4: a cache keyed on something unbounded and never evicted. Memory grows until
        # the container limit is reached - the code version of svc_mem_cap.
        "      strataCache.push({ url: url, at: Date.now(), pad: Buffer.alloc(65536) });\n"
        "    }\n"
        "    if (_bug === 'serial_awaits') {\n"
        # DEFECT 5: work that should be parallel done one at a time. Latency grows linearly
        # with the number of items, which looks exactly like a slow dependency.
        "      var _t = Date.now() + 40;\n"
        "      while (Date.now() < _t) { /* serialised wait, as if awaiting in a loop */ }\n"
        "    }\n"
        "    request.get(url, function(error, response, body) {",
        "event_loop_block, unbounded_cache and serial_awaits on the shared request path",
    ),
]

SERVICES = {"catalogue": CATALOGUE, "front-end": FRONTEND}

BUGS = {
    "catalogue": ["lock_across_io", "n_plus_one"],
    "front-end": ["event_loop_block", "unbounded_cache", "serial_awaits"],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--service", required=True, choices=sorted(SERVICES))
    ap.add_argument("--src", required=True, help="a CLEAN checkout of the service fork")
    ap.add_argument("--check", action="store_true", help="verify anchors only, write nothing")
    a = ap.parse_args()

    edits = SERVICES[a.service]
    problems, planned = [], []

    for rel, anchor, repl, note in edits:
        path = os.path.join(a.src, rel)
        if not os.path.isfile(path):
            problems.append(f"{rel}: file not found")
            continue
        text = open(path, encoding="utf-8").read()
        if "StrataTrace code-defect injection" in text and anchor not in text:
            planned.append(f"  SKIP  {rel}: already injected")
            continue
        n = text.count(anchor)
        if n == 0:
            problems.append(f"{rel}: ANCHOR NOT FOUND - upstream moved. Anchor was:\n"
                            f"      {anchor.splitlines()[0][:80]!r}")
        elif n > 1:
            problems.append(f"{rel}: anchor appears {n} times - ambiguous, refusing")
        else:
            planned.append(f"  OK    {rel}: {note}")

    for line in planned:
        print(line)
    if problems:
        print("\n*** REFUSING TO INJECT ***")
        for p in problems:
            print(f"  {p}")
        print("\nThe source has changed since these anchors were written. Fix the anchors -\n"
              "do NOT force it. A half-applied defect produces a run labelled as something it\n"
              "is not, and nothing downstream can tell.")
        return 1

    if a.check:
        print(f"\n{a.service}: all anchors present and unique. Defects available: "
              f"{', '.join(BUGS[a.service])}")
        return 0

    for rel, anchor, repl, _note in edits:
        path = os.path.join(a.src, rel)
        text = open(path, encoding="utf-8").read()
        if anchor in text:
            open(path, "w", encoding="utf-8", newline="\n").write(text.replace(anchor, repl, 1))
    print(f"\n{a.service}: defects injected. They are INERT until STRATA_BUG names one of: "
          f"{', '.join(BUGS[a.service])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
