#!/usr/bin/env python3
"""Turn a bare saved .html into a browser-style "Webpage, complete" save.

curl writes only the markup. Images, stylesheets and scripts still point at the network, so
the page renders bare once you are offline - which is not what the hand-downloaded pages in
folders 1-6 do. Those have a `<name>_files/` directory beside them and their links rewritten
to it.

This does the same thing:
  1. read the saved html, find every remote img / stylesheet / script
  2. download each into `<name>_files/`
  3. follow url(...) inside the downloaded CSS too, so fonts and background images come along
  4. rewrite the references to the local copies and write the html back

The original html is kept as `<name>.orig.html` the first time a page is processed, so a bad
rewrite can never destroy the only copy.

    python complete_pages.py                 # every bare page
    python complete_pages.py --dir misc
    python complete_pages.py --dry-run
"""
from __future__ import annotations
import argparse
import hashlib
import io
import os
import re
import sys
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
REFS = os.path.join(ROOT, "blueprint-references")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
MAX_ASSET = 8 * 1024 * 1024        # skip anything absurd; a page is not a video
TIMEOUT = 30
CSS_URL = re.compile(r"""url\(\s*['"]?([^'")]+)['"]?\s*\)""")

EXT_BY_TYPE = {
    "text/css": ".css", "application/javascript": ".js", "text/javascript": ".js",
    "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/svg+xml": ".svg",
    "image/webp": ".webp", "image/x-icon": ".ico", "font/woff2": ".woff2",
    "font/woff": ".woff", "font/ttf": ".ttf",
}


def base_url_of(html: str, fetched_from: str) -> str:
    """What relative URLs resolve against.

    This is the URL the page was FETCHED FROM, not what the page says about itself. A browser
    works the same way, and the difference is not academic: the PSI docs carry
    `canonical = https://facebook.github.io/psi/index.html` while actually living at
    facebookmicrosites.github.io, so trusting canonical sent every asset request to a dead host
    and silently lost the stylesheet and both logos.

    `<base href>` is the one thing that legitimately overrides, because it exists to.
    """
    soup = BeautifulSoup(html, "lxml")
    b = soup.find("base")
    if b and b.get("href"):
        return urljoin(fetched_from, b["href"])
    return fetched_from


def local_name(url: str, content_type: str) -> str:
    """A short, unique, filesystem-safe name - the browser does the same thing."""
    path = urlparse(url).path
    stem = os.path.basename(path) or "asset"
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", stem)[:60]
    root, ext = os.path.splitext(stem)
    if not ext:
        ext = EXT_BY_TYPE.get((content_type or "").split(";")[0].strip(), "")
        stem = root + ext
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    return "%s_%s" % (h, stem)


class Fetcher:
    def __init__(self, out_dir, dry=False):
        self.out = out_dir
        self.dry = dry
        self.seen = {}
        self.ok = 0
        self.failed = 0
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA})

    def get(self, url: str, referer: str = ""):
        """Download one asset. Returns its local filename, or None."""
        if url in self.seen:
            return self.seen[url]
        if url.startswith("data:") or not url.startswith(("http://", "https://")):
            return None
        try:
            r = self.s.get(url, timeout=TIMEOUT, stream=True,
                           headers={"Referer": referer} if referer else {})
            if r.status_code != 200:
                self.failed += 1
                self.seen[url] = None
                return None
            body = b""
            for chunk in r.iter_content(65536):
                body += chunk
                if len(body) > MAX_ASSET:
                    self.failed += 1
                    self.seen[url] = None
                    return None
        except Exception:                                                # noqa: BLE001
            self.failed += 1
            self.seen[url] = None
            return None

        name = local_name(url, r.headers.get("Content-Type", ""))
        if not self.dry:
            os.makedirs(self.out, exist_ok=True)
            with open(os.path.join(self.out, name), "wb") as fh:
                fh.write(body)
        self.seen[url] = name
        self.ok += 1

        # A stylesheet brings its own fonts and background images with it.
        if name.endswith(".css") and not self.dry:
            self._rewrite_css(os.path.join(self.out, name), url)
        return name

    def _rewrite_css(self, path: str, css_url: str):
        try:
            text = io.open(path, encoding="utf-8", errors="replace").read()
        except Exception:                                                # noqa: BLE001
            return
        changed = False
        for ref in set(CSS_URL.findall(text)):
            if ref.startswith(("data:", "#")):
                continue
            got = self.get(urljoin(css_url, ref), referer=css_url)
            if got:
                text = text.replace(ref, got)
                changed = True
        if changed:
            io.open(path, "w", encoding="utf-8").write(text)


def complete(html_path: str, page_url: str, dry: bool):
    stem = os.path.splitext(html_path)[0]
    out_dir = stem + "_files"
    raw = io.open(html_path, encoding="utf-8", errors="replace").read()
    base = base_url_of(raw, page_url)
    soup = BeautifulSoup(raw, "lxml")
    f = Fetcher(out_dir, dry)
    rel = os.path.basename(out_dir)

    def swap(tag, attr):
        v = tag.get(attr)
        if not v or v.startswith("data:"):
            return
        got = f.get(urljoin(base, v), referer=base)
        if got:
            tag[attr] = "%s/%s" % (rel, got)

    for t in soup.find_all("img"):
        swap(t, "src")
        if t.get("srcset"):
            del t["srcset"]          # keep one resolution; the browser does the same offline
    for t in soup.find_all("link"):
        if "stylesheet" in (t.get("rel") or []) or "icon" in " ".join(t.get("rel") or []):
            swap(t, "href")
    for t in soup.find_all("script"):
        if t.get("src"):
            swap(t, "src")

    if not dry:
        # keep the untouched download once, so a bad rewrite is always recoverable
        orig = stem + ".orig.html"
        if not os.path.exists(orig):
            io.open(orig, "w", encoding="utf-8").write(raw)
        io.open(html_path, "w", encoding="utf-8").write(str(soup))
    return f.ok, f.failed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    sys.path.insert(0, HERE)
    import yaml
    from fetch_refs import DIRS, safe
    man = yaml.safe_load(io.open(os.path.join(HERE, "manifest.yaml"), encoding="utf-8"))

    # map a saved file name back to the URL it came from
    url_of = {}
    for slug, m in man["sources"].items():
        u = m.get("url") or m.get("url_page")
        if not u:
            continue
        url_of[safe(m.get("title") or slug) + ".html"] = u
        if m.get("from"):
            url_of[os.path.basename(m["from"])] = u
        for x in (m.get("also") or []):
            url_of[os.path.basename(x)] = u

    total_ok = total_bad = pages = 0
    for d in sorted(os.listdir(REFS)):
        full = os.path.join(REFS, d)
        if not os.path.isdir(full):
            continue
        if a.dir and a.dir.lower() not in d.lower():
            continue
        for fn in sorted(os.listdir(full)):
            if not fn.lower().endswith(".html") or fn.endswith(".orig.html"):
                continue
            p = os.path.join(full, fn)
            if os.path.isdir(os.path.splitext(p)[0] + "_files"):
                continue                     # already complete (yours, or a previous run)
            u = url_of.get(fn)
            if not u:
                print("  SKIP (no url known) %s / %s" % (d[:28], fn[:50]))
                continue
            ok, bad = complete(p, u, a.dry_run)
            pages += 1
            total_ok += ok
            total_bad += bad
            print("  %-30s %-52s %3d assets%s"
                  % (d[:30], fn[:52], ok, "  (%d failed)" % bad if bad else ""))
    print()
    print("%d pages completed, %d assets saved, %d could not be fetched%s"
          % (pages, total_ok, total_bad, "  (dry run)" if a.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
