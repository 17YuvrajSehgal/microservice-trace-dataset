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
Every defect is gated at runtime on /dev/shm/strata_bug (then /tmp), falling back to the STRATA_BUG
environment variable. Reading a FILE is what lets a defect be switched on mid-run without
recreating the container - a restart inside the baseline window ruined 25 runs before this
was changed (CAMPAIGN-ISSUES 17). So a service builds
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
        'import (\n\t"errors"\n\t"io/ioutil"\n\t"os"\n\t"runtime"\n\t"strconv"\n\t"strings"\n\t"sync"\n\t"sync/atomic"\n\t"time"\n',
        "add os, io/ioutil, runtime, strconv, sync and sync/atomic for the defect gate",
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
        "var strataLeaks int64\n"
        "var strataStorm int64\n"
        "var strataFilesMu sync.Mutex\n"
        "var strataFiles []*os.File\n"
        "\n"
        "// TOGGLED THROUGH A FILE, NOT THE ENVIRONMENT. An environment variable cannot\n"
        "// change without recreating the container, and a restart inside the measured\n"
        "// baseline window is a far bigger event than any defect - it tears down every\n"
        "// connection. That silently ruined 25 runs. The environment variable stays as\n"
        "// the fallback, so an image started with STRATA_BUG set behaves as before.\n"
        "// Cached for a second: about one read per second, not one per request.\n"
        "var strataFlagMu sync.Mutex\n"
        "var strataFlagVal string\n"
        "var strataFlagAt time.Time\n"
        "\n"
        "func strataBug() string {\n"
        "\tstrataFlagMu.Lock()\n"
        "\tdefer strataFlagMu.Unlock()\n"
        "\tif !strataFlagAt.IsZero() && time.Since(strataFlagAt) < time.Second {\n"
        "\t\treturn strataFlagVal\n"
        "\t}\n"
        "\tv := os.Getenv(\"STRATA_BUG\")\n"
        "\t// /dev/shm FIRST. These services run with a READ-ONLY root filesystem, so\n"
        "\t// /tmp cannot be written. Measured on the VM: writing there failed with\n"
        "\t// \"Read-only file system\" and every defect reported\n"
        "\t// \"control would not start\". Docker mounts a tmpfs on /dev/shm\n"
        "\t// even when the rootfs is read-only, so it is the one writable path.\n"
        "\tfor _, p := range []string{\"/dev/shm/strata_bug\", \"/tmp/strata_bug\"} {\n"
        "\t\tif b, err := ioutil.ReadFile(p); err == nil {\n"
        "\t\t\tif s := strings.TrimSpace(string(b)); s != \"\" {\n"
        "\t\t\t\tv = s\n"
        "\t\t\t\tbreak\n"
        "\t\t\t}\n"
        "\t\t}\n"
        "\t}\n"
        "\tstrataFlagVal, strataFlagAt = v, time.Now()\n"
        "\treturn v\n"
        "}\n"
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
    (
        "service.go",
        "\t// DEMO: Change 0 to 850\n\ttime.Sleep(0 * time.Millisecond)\n",
        "\t// DEMO: Change 0 to 850\n\ttime.Sleep(0 * time.Millisecond)\n"
        # v5 DEFECT ctxswitch_storm: a pool of far too many threads that each wake up very often
        # and do nothing. Every wake-up is a context switch; each thread uses almost no CPU. The
        # first List request after the flag is set starts the pool; the threads end by themselves
        # when the flag changes. The flag may carry the pool size and the sleep in microseconds:
        # ctxswitch_storm:N:US (default 400 and 5000).
        "\tif b := strataBug(); strings.HasPrefix(b, \"ctxswitch_storm\") && atomic.CompareAndSwapInt64(&strataStorm, 0, 1) {\n"
        "\t\tn, us := 400, 5000\n"
        "\t\tif p := strings.Split(b, \":\"); len(p) == 3 {\n"
        "\t\t\tn, _ = strconv.Atoi(p[1])\n"
        "\t\t\tus, _ = strconv.Atoi(p[2])\n"
        "\t\t}\n"
        "\t\tgo func() {\n"
        "\t\t\tvar wg sync.WaitGroup\n"
        "\t\t\tfor i := 0; i < n; i++ {\n"
        "\t\t\t\twg.Add(1)\n"
        "\t\t\t\tgo func() {\n"
        "\t\t\t\t\tdefer wg.Done()\n"
        "\t\t\t\t\truntime.LockOSThread() // never unlocked: the thread ends with the goroutine\n"
        "\t\t\t\t\tfor k := 0; ; k++ {\n"
        "\t\t\t\t\t\tif k%100 == 0 && !strings.HasPrefix(strataBug(), \"ctxswitch_storm\") {\n"
        "\t\t\t\t\t\t\treturn\n"
        "\t\t\t\t\t\t}\n"
        "\t\t\t\t\t\ttime.Sleep(time.Duration(us) * time.Microsecond)\n"
        "\t\t\t\t\t}\n"
        "\t\t\t\t}()\n"
        "\t\t\t}\n"
        "\t\t\twg.Wait()\n"
        "\t\t\tatomic.StoreInt64(&strataStorm, 0)\n"
        "\t\t}()\n"
        "\t}\n"
        "\tswitch strataBug() {\n"
        # v3 DEFECT spin_loop: a busy-wait inside the handler. time.Since reads the clock through
        # the vDSO, so the loop makes no system call. Go serves other requests on other threads,
        # so requests are slower but still served - unlike event_loop_block in Node.
        "\tcase \"spin_loop\":\n"
        "\t\tt0 := time.Now()\n"
        "\t\tfor time.Since(t0) < 15*time.Millisecond {\n"
        "\t\t}\n"
        # v3 DEFECT thread_leak: every 10th List request starts a goroutine that locks itself to
        # an OS thread and blocks forever, so the thread is never given back. The process's thread
        # count only grows. (A plain goroutine would not do: it holds no OS thread while blocked.)
        "\tcase \"thread_leak\":\n"
        "\t\tif atomic.AddInt64(&strataLeaks, 1)%10 == 0 {\n"
        "\t\t\tgo func() { runtime.LockOSThread(); select {} }()\n"
        "\t\t}\n"
        # v3 DEFECT large_payload: the answer carries far more data than the caller needs (16 kB
        # of padding per item), with the same number of calls.
        "\tcase \"large_payload\":\n"
        "\t\tpad := strings.Repeat(\"x\", 16384)\n"
        "\t\tfor i := range socks {\n"
        "\t\t\tsocks[i].Description += pad\n"
        "\t\t}\n"
        # v4 DEFECT fd_leak: every 10th List request opens a file and keeps it; it is never
        # closed (the slice keeps a reference, so the garbage collector cannot close it either).
        # The process's descriptor count only grows.
        "\tcase \"fd_leak\":\n"
        "\t\tif atomic.AddInt64(&strataLeaks, 1)%10 == 0 {\n"
        "\t\t\tif f, err := os.Open(\"/app\"); err == nil {\n"
        "\t\t\t\tstrataFilesMu.Lock()\n"
        "\t\t\t\tstrataFiles = append(strataFiles, f)\n"
        "\t\t\t\tstrataFilesMu.Unlock()\n"
        "\t\t\t}\n"
        "\t\t}\n"
        # v4 DEFECT zombie_procs: every 10th List request starts a short child process (the
        # service's own binary with an unknown flag: it prints its usage and exits) and never
        # waits for it. Each child stays in the process table as a zombie until the service ends.
        "\tcase \"zombie_procs\":\n"
        "\t\tif atomic.AddInt64(&strataLeaks, 1)%10 == 0 {\n"
        "\t\t\t_, _ = os.StartProcess(\"/app\", []string{\"/app\", \"-strata-child\"}, &os.ProcAttr{})\n"
        "\t\t}\n"
        "\t}\n",
        "v3/v4: spin_loop, thread_leak, large_payload, fd_leak and zombie_procs on the List path",
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
        "  // TOGGLED THROUGH A FILE, NOT THE ENVIRONMENT - see the Go gate for why.\n"
        "  // The environment variable remains the fallback. Cached for a second.\n"
        "  var strataFlag = { v: null, at: 0 };\n"
        "  var strataBug = function () {\n"
        "    var now = Date.now();\n"
        "    if (strataFlag.v !== null && now - strataFlag.at < 1000) "
        "return strataFlag.v;\n"
        "    var v = process.env.STRATA_BUG || 'none';\n"
        "    // /dev/shm first: the rootfs is read-only, so /tmp cannot be written.\n"
        "    var paths = ['/dev/shm/strata_bug', '/tmp/strata_bug'];\n"
        "    for (var i = 0; i < paths.length; i++) {\n"
        "      try {\n"
        "        var s = require('fs').readFileSync(paths[i], 'utf8').trim();\n"
        "        if (s) { v = s; break; }\n"
        "      } catch (e) { /* try the next, then the environment */ }\n"
        "    }\n"
        "    strataFlag.v = v; strataFlag.at = now;\n"
        "    return v;\n"
        "  };\n"
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
        "    if (_bug.indexOf('regex_backtrack') === 0) {\n"
        # v3 DEFECT regex_backtrack: a nested quantifier on input that almost matches. V8's
        # backtracking engine takes exponential time on it. Only a small share of requests takes
        # this path, so the service stalls now and then, not always - unlike event_loop_block.
        # The flag may carry the input length and the share of requests: regex_backtrack:N:P
        # (default 26 and 0.002), so the fault can be calibrated without a rebuild.
        "      var _rp = _bug.split(':');\n"
        "      if (Math.random() < parseFloat(_rp[2] || '0.002')) {\n"
        "        /^(a+)+$/.test(new Array(parseInt(_rp[1] || '26', 10) + 1).join('a') + '!');\n"
        "      }\n"
        "    }\n"
        "    if (_bug === 'chatty_calls') {\n"
        # v4 DEFECT chatty_calls: three extra identical calls to the same service for every
        # request, whose answers are thrown away. Calls between the front-end and the service
        # rise four times; each answer is unchanged.
        "      for (var _c = 0; _c < 3; _c++) { request.get(url, function () {}); }\n"
        "    }\n"
        "    if (_bug.indexOf('blocking_wait') === 0) {\n"
        # v4 DEFECT blocking_wait: on a small share of requests the ONLY thread blocks in a
        # synchronous wait (Atomics.wait: a futex sleep) for some milliseconds. The thread is
        # OFF the CPU, unlike event_loop_block and regex_backtrack, but the service still stops.
        # The flag may carry the wait and the share: blocking_wait:MS:P (default 30 and 0.02).
        "      var _bw = _bug.split(':');\n"
        "      if (Math.random() < parseFloat(_bw[2] || '0.02')) {\n"
        "        Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, parseInt(_bw[1] || '30', 10));\n"
        "      }\n"
        "    }\n"
        # v5 DEFECT conn_churn: keep-alive is switched off for the calls to the service, so every
        # call opens a new TCP connection and closes it after one answer.
        "    var _ropt = (_bug === 'conn_churn') ? { url: url, forever: false, headers: { 'Connection': 'close' } } : url;\n"
        "    if (_bug === 'serial_awaits') {\n"
        # DEFECT 5: work that should be parallel done one at a time. Latency grows linearly
        # with the number of items, which looks exactly like a slow dependency.
        "      var _t = Date.now() + 40;\n"
        "      while (Date.now() < _t) { /* serialised wait, as if awaiting in a loop */ }\n"
        "    }\n"
        "    request.get(_ropt, function(error, response, body) {",
        "event_loop_block, unbounded_cache and serial_awaits on the shared request path",
    ),
]

SERVICES = {"catalogue": CATALOGUE, "front-end": FRONTEND}

BUGS = {
    "catalogue": ["lock_across_io", "n_plus_one", "spin_loop", "thread_leak", "large_payload", "fd_leak", "zombie_procs", "ctxswitch_storm"],
    "front-end": ["event_loop_block", "unbounded_cache", "serial_awaits", "regex_backtrack", "chatty_calls", "blocking_wait", "conn_churn"],
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
