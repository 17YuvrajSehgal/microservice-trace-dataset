#!/usr/bin/env python3
"""Check every blueprint's symptom words against the shared list, and measure how much work
selection actually has to do.

WHY THIS EXISTS
---------------
Before the shared list, each blueprint invented its own symptom words. 24 words across 11
blueprints, and 22 of them used by exactly one blueprint. Selection by word matching would
have scored near-perfect, because each word named its own answer. That is not selection
working. That is the answer written into the question.

This checker fails a blueprint that uses a private word, and reports the number that says
whether selection is a real problem at all:

    DISTINCTNESS - the share of blueprints whose word set is unique.
    If every set is unique, matching is trivially correct and proves nothing.
    Overlap is what forces selection to do work.

    ORACLE CEILING - how many blueprints a perfect word-matcher would leave on the shortlist.
    A ceiling of 1.0 means words alone decide it. Anything above 1 means the confirm step
    has to break the tie, which is the honest case.

    python3 check_symptoms.py [--blueprints DIR] [--symptoms FILE] [--strict]

--strict exits non-zero on any violation, for CI.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load_vocab(path):
    doc = json.load(open(path, encoding="utf-8"))
    words = {}
    for axis, spec in doc.get("axes", {}).items():
        for w, wspec in spec.get("words", {}).items():
            words[w] = {"axis": axis, **wspec}
    return doc, words


def load_blueprints(d):
    out = {}
    for p in sorted(glob.glob(os.path.join(d, "*", "blueprint.json"))):
        try:
            b = json.load(open(p, encoding="utf-8"))
        except Exception as e:
            print("  could not read %s: %s" % (p, e))
            continue
        out[b.get("id", os.path.basename(os.path.dirname(p)))] = b
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blueprints", default=os.path.join(ROOT, "problems"))
    ap.add_argument("--symptoms", default=os.path.join(ROOT, "symptoms.json"))
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()

    doc, vocab = load_vocab(a.symptoms)
    bps = load_blueprints(a.blueprints)
    print("shared list: %d words, status=%s" % (len(vocab), doc.get("status")))
    print("blueprints : %d\n" % len(bps))

    problems = []
    claimed = {}
    for bid, b in sorted(bps.items()):
        words = b.get("selection", {}).get("applicable_symptoms", []) or []
        claimed[bid] = set(words)
        unknown = [w for w in words if w not in vocab]
        if unknown:
            problems.append((bid, "uses words not in the shared list: %s" % ", ".join(sorted(unknown))))
        if not words:
            problems.append((bid, "declares no symptom words"))
        unmeasurable = [w for w in words if w in vocab and not vocab[w].get("measured_by")]
        if unmeasurable:
            problems.append((bid, "uses words nothing can measure: %s" % ", ".join(sorted(unmeasurable))))

    # how many blueprints claim each word
    by_word = collections.Counter()
    for ws in claimed.values():
        for w in ws:
            by_word[w] += 1

    print("word use (only words some blueprint claims):")
    for w, n in sorted(by_word.items(), key=lambda kv: (-kv[1], kv[0])):
        flag = "  <- only one blueprint" if n == 1 else ""
        print("  %-44s %d%s" % (w, n, flag))
    singles = [w for w, n in by_word.items() if n == 1]
    print("\n  words claimed by exactly one blueprint: %d of %d" % (len(singles), len(by_word)))

    for bid, ws in sorted(claimed.items()):
        if ws and all(by_word[w] == 1 for w in ws):
            problems.append((bid, "every word it uses is unique to it - it names its own answer"))

    # DISTINCTNESS and ORACLE CEILING
    sets = {b: frozenset(w) for b, w in claimed.items() if w}
    if sets:
        seen = collections.Counter(sets.values())
        unique = sum(1 for s in sets.values() if seen[s] == 1)
        print("\n  distinctness: %d of %d blueprints have a word set no other blueprint has (%.0f%%)"
              % (unique, len(sets), 100.0 * unique / len(sets)))

        # A perfect matcher sees the true blueprint's own words and keeps every blueprint whose
        # words are a subset of what it observed. That is the best any word-matcher can do.
        ceil = []
        for truth, tw in sets.items():
            kept = [b for b, w in sets.items() if w and w <= tw]
            ceil.append(len(kept))
        avg = sum(ceil) / len(ceil)
        print("  oracle ceiling: a perfect word-matcher leaves %.2f blueprints on the shortlist"
              % avg)
        if avg <= 1.05:
            print("    WARNING: words alone decide it. Selection is not being tested.")
        else:
            print("    good: the confirm step has to break ties, which is the honest case.")

    print()
    if problems:
        print("PROBLEMS (%d):" % len(problems))
        for bid, msg in problems:
            print("  %-30s %s" % (bid, msg))
    else:
        print("no problems found.")

    if a.strict and problems:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
