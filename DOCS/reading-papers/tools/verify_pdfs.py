#!/usr/bin/env python3
"""Check every downloaded PDF is actually the paper it claims to be.

This exists because of a near miss. A guessed URL at an institutional repository returned
HTTP 200 with a perfectly valid PDF - of a completely different paper (power flow in LVDC
grids, where we wanted kernel tracing). A magic-bytes check passes that file happily. The only
way to catch it is to read the first page and look for words the real paper must contain.

    python verify_pdfs.py
"""
from __future__ import annotations
import io
import os
import re
import sys

import yaml
from pypdf import PdfReader

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
REFS = os.path.join(ROOT, "blueprint-references")
sys.path.insert(0, HERE)
from fetch_refs import DIRS, safe                                        # noqa: E402

STOP = {"the", "a", "an", "of", "for", "and", "in", "to", "on", "with", "at", "by", "from",
        "using", "their", "its", "how", "not", "your", "study", "wild", "approach", "through",
        "into", "deep", "dive", "real", "world", "real-time", "analysis", "systems", "system"}


def first_page_text(path: str, pages: int = 2) -> str:
    try:
        r = PdfReader(path)
        return " ".join((r.pages[i].extract_text() or "")
                        for i in range(min(pages, len(r.pages))))
    except Exception as e:                                               # noqa: BLE001
        return "!!ERROR %r" % e


def keywords(title: str):
    words = re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", title.lower())
    return [w for w in words if w not in STOP][:8]


def main() -> int:
    man = yaml.safe_load(io.open(os.path.join(HERE, "manifest.yaml"), encoding="utf-8"))
    bad = []
    checked = 0
    for slug, meta in sorted(man["sources"].items()):
        if meta.get("kind") not in ("pdf", "local"):
            continue
        title = meta.get("title") or slug
        for bp in meta.get("blueprints", []):
            d = os.path.join(REFS, DIRS[bp])
            cand = (os.path.join(d, "%s.pdf" % safe(title)) if meta["kind"] == "pdf"
                    else os.path.join(d, os.path.basename(meta.get("from", ""))))
            if not cand.lower().endswith(".pdf") or not os.path.exists(cand):
                continue
            txt = first_page_text(cand).lower()
            checked += 1
            if txt.startswith("!!error"):
                bad.append((slug, bp, "unreadable: %s" % txt[:60]))
                break
            kws = keywords(title)
            hits = [k for k in kws if k in txt]
            # a scanned/proceedings PDF may extract almost nothing; say so rather than
            # pretending it failed the title check
            # Known-good shapes first, so they are not re-reported every run:
            #   pages        -> a whole proceedings volume; its cover page says nothing about
            #                   the paper, which starts deeper in (verified once, by hand)
            #   no_text_layer-> scanned images, e.g. a USPTO patent
            if meta.get("pages") or meta.get("no_text_layer"):
                pass
            elif len(txt.strip()) < 200:
                bad.append((slug, bp, "no extractable text (scanned?) - check by eye"))
            elif len(hits) < max(1, len(kws) // 3):
                bad.append((slug, bp, "title words %s; matched only %s" % (kws[:5], hits)))
            break
    print("%d PDFs checked, %d need a look" % (checked, len(bad)))
    for slug, bp, why in bad:
        print("  [%2d] %-34s %s" % (bp, slug, why))
    return 0


if __name__ == "__main__":
    sys.exit(main())
