#!/usr/bin/env python3
"""Build reading-papers/sources/ and index.yaml from the numbered reading directories.

Two views of the same material, on purpose:

  blueprint-references/<N> ...   for READING - one folder per problem, a source that serves
                                 three blueprints appears in all three
  sources/<slug>/               for CITING - one folder per source, no duplicates, each with
                                 a meta.yaml carrying doi/arxiv/url/type/status
  index.yaml                    which source supports which blueprint

The numbered directories stay exactly as they are. This adds the second view beside them; it
never moves or deletes anything.

    python build_sources.py [--dry-run]
"""
from __future__ import annotations
import argparse
import datetime
import io
import os
import re
import shutil
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
REFS = os.path.join(ROOT, "blueprint-references")
SRCS = os.path.join(ROOT, "sources")

sys.path.insert(0, HERE)
from fetch_refs import DIRS, safe                                        # noqa: E402


def find_in_dirs(meta: dict, slug: str):
    """Locate the files this source produced, in any numbered directory it belongs to.

    Looks for what the fetcher would have written, then falls back to the hand-downloaded
    name recorded in `from`, so sources downloaded before this tool existed are still found.
    """
    title = safe(meta.get("title") or slug)
    wanted = []
    kind = meta.get("kind")
    if kind in ("pdf", "raw"):
        wanted = ["%s.%s" % (title, meta.get("ext", "pdf"))]
    elif kind == "html":
        wanted = ["%s.html" % title, "%s.md" % title]
    elif kind == "text":
        wanted = ["%s.txt" % title, "%s.md" % title]
    elif kind == "md":
        wanted = ["%s.md" % title]
    elif kind == "local":
        wanted = [os.path.basename(meta["from"])]
        wanted += [os.path.basename(x) for x in (meta.get("also") or [])]

    found = []
    for bp in meta.get("blueprints", []):
        d = os.path.join(REFS, DIRS[bp])
        for w in wanted:
            p = os.path.join(d, w)
            if os.path.exists(p) and not any(os.path.basename(f) == w for f in found):
                found.append(p)
    return found


def blueprint_id(n: int) -> str:
    """'3 connection-pool-exhaustion (conn_pool_exhaustion)' -> 'connection-pool-exhaustion'."""
    label = DIRS[n]
    label = re.sub(r"^\d+\s+", "", label)          # drop the leading number
    label = re.sub(r"\s*\(.*\)\s*$", "", label)   # drop the "(family)" suffix
    return label.strip()


def retrieved_on(paths) -> str:
    """When this source was actually downloaded, from the newest file's mtime.

    Better than stamping today's date on everything: the hand-downloaded pages in folders 1-6
    were fetched weeks ago and should say so.
    """
    ts = [os.path.getmtime(p) for p in paths if os.path.exists(p)]
    return datetime.date.fromtimestamp(max(ts)).isoformat() if ts else ""


def dest_name(path: str, meta: dict) -> str:
    """paper.pdf / page.md / page.html - the canonical names asked for."""
    ext = os.path.splitext(path)[1].lower()
    doc = meta.get("type") in ("peer_reviewed",) or meta.get("kind") in ("pdf",)
    if ext == ".pdf":
        return "paper.pdf"
    if ext == ".md":
        return "paper.md" if doc else "page.md"
    if ext in (".html", ".htm"):
        return "page.html"
    if ext == ".txt":
        return "page.txt"
    return os.path.basename(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    man = yaml.safe_load(io.open(os.path.join(HERE, "manifest.yaml"), encoding="utf-8"))
    sources = man["sources"]

    index = {"blueprints": {}, "sources": {}}
    built = missing = 0

    for slug, meta in sorted(sources.items()):
        files = find_in_dirs(meta, slug)
        out = os.path.join(SRCS, slug)
        if not a.dry_run:
            os.makedirs(out, exist_ok=True)

        copied = []
        for f in files:
            dn = dest_name(f, meta)
            # paper.md is a HAND-WRITTEN summary of the paper, not an extract of it. Nothing
            # generated may overwrite one. Today no PDF source produces a .md so the clash
            # cannot happen, but that is luck, not design - one trafilatura run on a landing
            # page would destroy a summary that took real work.
            if dn == "paper.md" and os.path.exists(os.path.join(out, dn)):
                copied.append(dn)
                continue
            if not a.dry_run:
                shutil.copy2(f, os.path.join(out, dn))
                # An .html without its assets renders bare, which defeats the point of having
                # saved them. Bring the `<name>_files/` directory across as `page_files/` and
                # repoint the copy at it, since the file was renamed on the way in.
                if dn.endswith(".html"):
                    src_assets = os.path.splitext(f)[0] + "_files"
                    if os.path.isdir(src_assets):
                        dst_assets = os.path.join(out, "page_files")
                        shutil.copytree(src_assets, dst_assets, dirs_exist_ok=True)
                        dst_html = os.path.join(out, dn)
                        txt = io.open(dst_html, encoding="utf-8", errors="replace").read()
                        txt = txt.replace(os.path.basename(src_assets) + "/", "page_files/")
                        io.open(dst_html, "w", encoding="utf-8").write(txt)
                        copied.append("page_files/")
            copied.append(dn)

        meta_out = {
            "id": slug,
            "title": meta.get("title"),
            "authors": meta.get("authors"),
            "year": meta.get("year"),
            "venue": meta.get("venue"),
            "doi": meta.get("doi"),
            "url": meta.get("url") or meta.get("url_page"),
            # when it was actually fetched, and - for anything backed by git - exactly which
            # revision. A wiki page or a README changes under you; a DOI does not.
            "retrieved": retrieved_on(files),
            "commit": meta.get("commit"),
            # strength and verification, mirroring the reference pack's own tags so a reader
            # can tell a read-and-checked source from one seen only in a search snippet
            "type": meta.get("type"),
            "status": meta.get("status"),
            "verified": meta.get("status") == "V",
            "blueprints": [blueprint_id(n) for n in meta.get("blueprints", [])],
            "files": sorted(copied),
        }
        if not meta_out["commit"]:
            del meta_out["commit"]          # only present where it means something
        # a key with `null` under it tells a reader nothing; leave it out
        for k in ("authors", "year", "venue", "doi", "retrieved"):
            if meta_out.get(k) in (None, ""):
                meta_out.pop(k, None)
        if meta.get("note"):
            meta_out["note"] = meta["note"]
        if meta.get("url_note"):
            meta_out["url_note"] = meta["url_note"]
        if not copied:
            meta_out["files"] = []
            meta_out["note"] = ((meta_out.get("note", "") + " ")
                                + "NOT DOWNLOADED - see index.yaml missing list").strip()
            missing += 1
        else:
            built += 1

        if not a.dry_run:
            yaml.safe_dump(meta_out, io.open(os.path.join(out, "meta.yaml"), "w",
                                             encoding="utf-8"),
                           sort_keys=False, allow_unicode=True)

        index["sources"][slug] = {"title": meta.get("title"),
                                  "have": bool(copied), "files": sorted(copied)}
        for bp in meta.get("blueprints", []):
            index["blueprints"].setdefault(blueprint_id(bp), []).append(slug)

    # keep blueprint order numeric (1,2,...,16), not the lexicographic 1,10,11,...
    ordered = {}
    for n in sorted(DIRS):
        k = blueprint_id(n)
        if k in index["blueprints"]:
            ordered[k] = sorted(set(index["blueprints"][k]))
    index["blueprints"] = ordered
    index["missing"] = sorted(s for s, v in index["sources"].items() if not v["have"])

    if not a.dry_run:
        os.makedirs(SRCS, exist_ok=True)
        with io.open(os.path.join(ROOT, "index.yaml"), "w", encoding="utf-8") as fh:
            fh.write("# Which source supports which blueprint.\n"
                     "# Generated by tools/build_sources.py - do not hand-edit; edit "
                     "tools/manifest.yaml instead.\n"
                     "# `missing` lists sources with no file on disk yet.\n\n")
            yaml.safe_dump(index, fh, sort_keys=False, allow_unicode=True)

    print("%d sources with files, %d still empty%s"
          % (built, missing, "  (dry run)" if a.dry_run else ""))
    if index["missing"]:
        print("empty:")
        for s in index["missing"]:
            print("   %s" % s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
