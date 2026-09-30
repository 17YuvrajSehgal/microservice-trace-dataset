#!/usr/bin/env python3
"""Extract a PDF's text so it can be read and summarised.

The Read tool renders PDFs as images, which needs poppler; that is not installed here. These
are text-layer PDFs, so pulling the text directly is both possible and cheaper.

    python pdf_text.py <slug>            # writes .cache/<slug>.txt and prints a size report
    python pdf_text.py <slug> --stdout   # print it instead
"""
from __future__ import annotations
import argparse
import io
import os
import re
import sys
import warnings

warnings.filterwarnings("ignore")
from pypdf import PdfReader                                             # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SRCS = os.path.join(ROOT, "sources")
CACHE = os.path.join(HERE, ".cache")


def clean(t: str) -> str:
    """Undo the two things that make extracted PDF text hard to read."""
    t = t.replace("­", "")                       # soft hyphens
    t = re.sub(r"-\n(?=[a-z])", "", t)                # words split across a line break
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def extract(pdf: str, first: int = 0, last: int = 10 ** 6) -> str:
    r = PdfReader(pdf)
    out = []
    for i, page in enumerate(r.pages, start=1):
        if i < first or i > last:
            continue
        try:
            out.append("\n\n===== PAGE %d =====\n%s" % (i, page.extract_text() or ""))
        except Exception as e:                                          # noqa: BLE001
            out.append("\n\n===== PAGE %d ===== [extract failed: %r]" % (i, e))
    return clean("".join(out))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--first", type=int, default=0)
    ap.add_argument("--last", type=int, default=10 ** 6)
    ap.add_argument("--stdout", action="store_true")
    a = ap.parse_args()

    pdf = os.path.join(SRCS, a.slug, "paper.pdf")
    if not os.path.exists(pdf):
        print("no paper.pdf for %s" % a.slug)
        return 1
    txt = extract(pdf, a.first, a.last)
    if a.stdout:
        sys.stdout.write(txt)
        return 0
    os.makedirs(CACHE, exist_ok=True)
    out = os.path.join(CACHE, a.slug + ".txt")
    io.open(out, "w", encoding="utf-8").write(txt)
    print("%s: %d pages of text, %d chars -> %s"
          % (a.slug, txt.count("===== PAGE"), len(txt), out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
