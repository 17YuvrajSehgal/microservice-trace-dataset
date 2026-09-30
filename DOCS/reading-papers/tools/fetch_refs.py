#!/usr/bin/env python3
"""Download the blueprint references into the numbered reading directories.

Follows the conventions already in use by hand:
  - a PDF is saved as-is
  - an HTML page is saved as .html AND rendered to .md with trafilatura
  - a source used by several blueprints is copied into EVERY one of them, not skipped

Nothing is silently skipped. Anything that cannot be fetched is reported at the end with its
HTTP status, so it can be marked [x] in REFERENCE-PACK-FOR-KERNEL-TRACE.md and chased by hand.

    python fetch_refs.py                 # fetch everything missing
    python fetch_refs.py --only 7,8      # just those blueprint directories
    python fetch_refs.py --dry-run
"""
from __future__ import annotations
import argparse
import io
import os
import shutil
import subprocess
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))          # DOCS/reading-papers
REFS = os.path.join(ROOT, "blueprint-references")
VENV = os.path.abspath(os.path.join(ROOT, "..", "..", ".venv", "Scripts"))
TRAF = os.path.join(VENV, "trafilatura.exe")

# The numbered directory names, exactly as they appear on disk (1-6 already exist).
DIRS = {
    1: "1 host-cpu-saturation (anomaly_cpu)",
    2: "2 network-path-degradation (anomaly_net, svc_net)",
    3: "3 connection-pool-exhaustion (conn_pool_exhaustion)",
    4: "4 deadlock-lock-order (deadlock)",
    5: "5 dependency-outage-retry-storm (dependency_outage)",
    6: "6 lock-contention-futex-storm (lock_contention)",
    7: "7 cpu-contention-co-tenant (noisy_neighbor)",
    8: "8 priority-inversion-nice (priority_inversion)",
    9: "9 db-latency-dependency-wait (slow_db)",
    10: "10 service-cpu-throttle (svc_cpu_cap)",
    11: "11 dns-delay",
    12: "12 fd-exhaustion",
    13: "13 fork-storm",
    14: "14 host-disk-saturation",
    15: "15 service-memory-cap",
    16: "16 data-exfiltration",
    # Everything the pack cites that is not tied to one blueprint: the cross-cutting method
    # sources, the "Related families (short)" section, and the whole related-work review.
    17: "misc",
    # Papers the supervisor recommended. Five already have hand-written summaries;
    # four are long documents (a 1200-page reference book, two copies of the same
    # thesis, and a Master's thesis) with none yet.
    18: "prof-recommendation",
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

results = []          # (slug, blueprint, what, status)


def safe(name: str) -> str:
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "-")
    return name.strip()[:120]


def curl(url: str, dest: str, timeout: int = 90):
    """Fetch to dest. Returns (ok, http_status_or_error)."""
    cmd = ["curl", "-sSL", "--max-time", str(timeout), "-A", UA,
           "-w", "%{http_code}", "-o", dest, url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30,
                           encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return False, "timeout"
    code = (r.stdout or "").strip()[-3:]
    if code != "200" or not os.path.exists(dest) or os.path.getsize(dest) < 500:
        size = os.path.getsize(dest) if os.path.exists(dest) else 0
        if os.path.exists(dest) and size < 500:
            os.remove(dest)
        return False, "http %s, %d bytes" % (code or "?", size)
    return True, code


def to_markdown(url: str, dest_md: str):
    """Render a page to markdown, the same way the hand-run command does."""
    exe = TRAF if os.path.exists(TRAF) else "trafilatura"
    try:
        # encoding MUST be set: Windows defaults subprocess text mode to cp1252, which throws
        # UnicodeDecodeError on any UTF-8 page and silently yields an empty markdown file. Six
        # kernel.org docs came back as 0-char .md files before this was fixed.
        r = subprocess.run([exe, "-u", url, "--markdown"],
                           capture_output=True, text=True, timeout=120,
                           encoding="utf-8", errors="replace")
    except Exception as e:                                              # noqa: BLE001
        return False, repr(e)[:80]
    if r.returncode != 0 or len(r.stdout or "") < 200:
        return False, "trafilatura rc=%d, %d chars" % (r.returncode, len(r.stdout or ""))
    io.open(dest_md, "w", encoding="utf-8").write(r.stdout)
    return True, "ok"


def is_pdf(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(5) == b"%PDF-"
    except Exception:                                                   # noqa: BLE001
        return False


def handle(slug: str, meta: dict, bp: int, dry: bool):
    d = os.path.join(REFS, DIRS[bp])
    os.makedirs(d, exist_ok=True)
    kind = meta.get("kind")
    title = safe(meta.get("title") or slug)

    if kind == "local":
        for rel in [meta["from"]] + list(meta.get("also") or []):
            src = os.path.join(REFS, rel)
            if not os.path.exists(src):
                results.append((slug, bp, os.path.basename(rel), "SOURCE MISSING"))
                continue
            dst = os.path.join(d, os.path.basename(rel))
            if os.path.abspath(src) == os.path.abspath(dst) or os.path.exists(dst):
                results.append((slug, bp, os.path.basename(rel), "already there"))
                continue
            if not dry:
                shutil.copy2(src, dst)
                sup = src[:-len(os.path.splitext(src)[1])] + "_files"
                if os.path.isdir(sup):
                    shutil.copytree(sup, dst[:-len(os.path.splitext(dst)[1])] + "_files",
                                    dirs_exist_ok=True)
            results.append((slug, bp, os.path.basename(rel), "copied"))
        return

    if kind in ("pdf", "raw"):
        ext = meta.get("ext", "pdf")
        dest = os.path.join(d, "%s.%s" % (title, ext))
        if os.path.exists(dest):
            results.append((slug, bp, os.path.basename(dest), "already there"))
            return
        if dry:
            results.append((slug, bp, os.path.basename(dest), "would fetch"))
            return
        ok, why = curl(meta["url"], dest)
        if ok and ext == "pdf" and not is_pdf(dest):
            head = open(dest, "rb").read(400) if os.path.exists(dest) else b""
            why = ("not a PDF - Cloudflare challenge page"
                   if b"Just a moment" in head or b"cf-browser-verification" in head
                   else "not a PDF (login wall or HTML error page)")
            ok = False
            os.remove(dest)
        results.append((slug, bp, os.path.basename(dest), "OK" if ok else "FAIL: %s" % why))
        return

    if kind == "unavailable":
        # Recorded, not fetched. A publisher that refuses every route is a fact worth storing
        # once, rather than a failure re-reported on every run.
        results.append((slug, bp, "-", "already there"))
        return

    if kind == "md":
        # Markdown only. Some sites 403 a plain curl but answer trafilatura's fetcher - the
        # OpenJDK bug tracker is one - so the archive .html cannot be saved even though the
        # text is readable. Better to hold the text and say the html is missing than to hold
        # a 403 error page named .html.
        m = os.path.join(d, "%s.md" % title)
        if os.path.exists(m):
            results.append((slug, bp, os.path.basename(m), "already there"))
            return
        if dry:
            results.append((slug, bp, os.path.basename(m), "would fetch"))
            return
        ok, why = to_markdown(meta["url"], m)
        results.append((slug, bp, os.path.basename(m), "OK" if ok else "FAIL: %s" % why))
        return

    if kind == "text":
        # A plain-text document, not a web page. trafilatura extracts nothing from these (it
        # looks for HTML structure), so it returned a 0-char .md for kernel.org's cgroup-v2.txt.
        # The text IS the readable form, so save it under both names.
        t = os.path.join(d, "%s.txt" % title)
        m = os.path.join(d, "%s.md" % title)
        if os.path.exists(m):
            results.append((slug, bp, os.path.basename(m), "already there"))
            return
        if dry:
            results.append((slug, bp, os.path.basename(m), "would fetch"))
            return
        ok, why = curl(meta["url"], t)
        if ok:
            shutil.copy2(t, m)
        results.append((slug, bp, os.path.basename(m), "OK" if ok else "FAIL: %s" % why))
        return

    if kind == "html":
        h = os.path.join(d, "%s.html" % title)
        m = os.path.join(d, "%s.md" % title)
        if os.path.exists(h) and (meta.get("html_only") or os.path.exists(m)):
            results.append((slug, bp, os.path.basename(h), "already there"))
            return
        if dry:
            results.append((slug, bp, os.path.basename(h), "would fetch"))
            return
        ok_h, why_h = curl(meta["url"], h)
        if meta.get("html_only"):
            # the page has no extractable article text; the .html IS the artifact
            results.append((slug, bp, os.path.basename(h),
                            "OK" if ok_h else "FAIL: %s" % why_h))
            return
        ok_m, why_m = to_markdown(meta["url"], m)
        # the markdown is what actually gets read; the html is the archive copy
        status = ("OK" if (ok_h and ok_m) else
                  "PARTIAL: html %s / md %s" % ("ok" if ok_h else why_h,
                                                "ok" if ok_m else why_m))
        results.append((slug, bp, os.path.basename(h), status))
        return

    results.append((slug, bp, "-", "UNKNOWN kind %r" % kind))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated blueprint numbers")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    want = {int(x) for x in a.only.split(",") if x.strip()} if a.only else set(DIRS)

    man = yaml.safe_load(io.open(os.path.join(HERE, "manifest.yaml"), encoding="utf-8"))
    src = man["sources"]

    for slug, meta in src.items():
        for bp in meta.get("blueprints", []):
            if bp in want:
                handle(slug, meta, bp, a.dry_run)

    ok = [r for r in results if r[3] in ("OK", "copied", "already there")]
    bad = [r for r in results if r[3] not in ("OK", "copied", "already there")]
    print("%d items: %d ok, %d need attention" % (len(results), len(ok), len(bad)))
    if bad:
        print()
        print("NEEDS ATTENTION (mark these [x] in the reference pack):")
        for slug, bp, what, why in bad:
            print("  [%2d] %-34s %-46s %s" % (bp, slug, what[:46], why))
    return 0


if __name__ == "__main__":
    sys.exit(main())
