#!/usr/bin/env python3
"""Is each saved .html a real page, and is it self-contained?

Two different failures, and a file can have either:

  CONTENT   the bytes on disk are not the article - a Cloudflare challenge, a cookie wall, or
            a JavaScript shell that renders nothing without a browser. Size alone cannot tell
            you: a 300 KB JS shell looks healthier than a 15 KB plain-HTML paper.

  ASSETS    the page is real, but curl saved only the markup. Images, CSS and fonts still
            point at the network, so it renders bare offline. A browser's "Webpage, complete"
            writes a `<name>_files/` directory beside the html and rewrites the links; that is
            the behaviour the hand-downloaded pages in 1-6 have and these do not.

    python audit_html.py [--dir "misc"]
"""
from __future__ import annotations
import argparse
import io
import os
import re
import sys

from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
REFS = os.path.join(ROOT, "blueprint-references")

CHALLENGE = ("just a moment", "cf-browser-verification", "checking your browser",
             "enable javascript and cookies", "ddos protection by", "captcha-bypass",
             "access denied", "403 forbidden", "are you a robot")

# Text under this many characters is not an article. Measured against the hand-saved pages,
# which run from about 6,000 (a short kernel doc) upwards.
MIN_TEXT = 1200


def visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    return " ".join(soup.get_text(" ").split())


def external_assets(html: str) -> dict:
    """Count references that still point at the network."""
    soup = BeautifulSoup(html, "lxml")
    out = {"img": 0, "css": 0, "js": 0}
    for t in soup.find_all("img"):
        src = t.get("src") or t.get("data-src") or ""
        if src.startswith(("http://", "https://", "//")):
            out["img"] += 1
    for t in soup.find_all("link"):
        if "stylesheet" in (t.get("rel") or []) and str(t.get("href", "")).startswith(
                ("http://", "https://", "//")):
            out["css"] += 1
    for t in soup.find_all("script"):
        if str(t.get("src", "")).startswith(("http://", "https://", "//")):
            out["js"] += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="", help="only this directory name")
    a = ap.parse_args()

    rows = []
    for d in sorted(os.listdir(REFS)):
        full = os.path.join(REFS, d)
        if not os.path.isdir(full):
            continue
        if a.dir and a.dir.lower() not in d.lower():
            continue
        for f in sorted(os.listdir(full)):
            if not f.lower().endswith((".html", ".htm")):
                continue
            if f.endswith(".orig.html"):
                continue        # the untouched pre-rewrite backup; it is meant to be bare
            p = os.path.join(full, f)
            raw = io.open(p, encoding="utf-8", errors="replace").read()
            low = raw[:4000].lower()
            txt = visible_text(raw)
            ext = external_assets(raw)
            has_files_dir = os.path.isdir(os.path.join(full, os.path.splitext(f)[0] + "_files"))

            problems = []
            if any(c in low for c in CHALLENGE):
                problems.append("CHALLENGE/BLOCK PAGE")
            elif len(txt) < MIN_TEXT:
                problems.append("only %d chars of text - JS shell?" % len(txt))
            if not has_files_dir and (ext["img"] or ext["css"]):
                problems.append("no _files (img %d, css %d still remote)"
                                % (ext["img"], ext["css"]))
            rows.append((d, f, len(raw), len(txt), has_files_dir, problems))

    bad_content = [r for r in rows if any("CHALLENGE" in p or "JS shell" in p
                                          for p in r[5])]
    bare = [r for r in rows if any("no _files" in p for p in r[5])]
    ok = [r for r in rows if not r[5]]

    print("%d html files: %d fine, %d bare (no assets), %d with a CONTENT problem"
          % (len(rows), len(ok), len(bare), len(bad_content)))
    print()
    if bad_content:
        print("CONTENT PROBLEMS - the page itself is not there:")
        for d, f, nb, nt, hf, pr in bad_content:
            print("  [%s]" % d[:34])
            print("     %-62s %s" % (f[:62], "; ".join(pr)))
        print()
    if bare:
        print("BARE - real page, but images/CSS still point at the network:")
        for d, f, nb, nt, hf, pr in bare:
            print("  %-34s %-56s text=%d" % (d[:34], f[:56], nt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
