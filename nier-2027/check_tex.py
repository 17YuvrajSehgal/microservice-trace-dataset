#!/usr/bin/env python3
"""Static sanity checks for paper.tex -- no TeX engine on this machine."""
import re, sys, os

p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper.tex")
s = open(p, encoding="utf-8").read()

ok = True
bal = s.count("{") - s.count("}")
print("brace balance          :", bal)
ok &= bal == 0

envs = re.findall(r"\\begin\{(\w+\*?)\}", s)
for e in sorted(set(envs)):
    b = len(re.findall(r"\\begin\{%s\}" % re.escape(e), s))
    n = len(re.findall(r"\\end\{%s\}" % re.escape(e), s))
    flag = "" if b == n else "   <-- MISMATCH"
    print(f"env {e:<12}: {b} begin / {n} end{flag}")
    ok &= b == n

cites = set(re.findall(r"\\cite\{([^}]*)\}", s))
keys = set()
for c in cites:
    keys.update(k.strip() for k in c.split(","))
bibkeys = set(re.findall(r"\\bibitem\{([^}]+)\}", s))
if not bibkeys:
    bib = open(p.replace("paper.tex", "refs.bib"), encoding="utf-8").read()
    bibkeys = set(re.findall(r"@\w+\{([^,]+),", bib))
missing = keys - bibkeys
unused = bibkeys - keys
print("cite keys used         :", sorted(keys))
print("missing from refs.bib  :", sorted(missing) or "none")
print("in bib but never cited :", sorted(unused) or "none")
ok &= not missing

refs = set(re.findall(r"\\ref\{([^}]+)\}", s))
labels = set(re.findall(r"\\label\{([^}]+)\}", s))
dangling = refs - labels
print("dangling \\ref          :", sorted(dangling) or "none")
ok &= not dangling

todos = re.findall(r"\\TODO\{[^}]*\}", s)
print("TODO uses              :", len(todos))
ok &= len(todos) == 0

figs = re.findall(r"\\includegraphics\[[^]]*\]\{([^}]+)\}", s)
for f in figs:
    path = os.path.join(os.path.dirname(p), f)
    exists = os.path.exists(path)
    print(f"figure {f:<18}: {'exists' if exists else 'MISSING'}")
    ok &= exists

print("words (approx)         :", len(re.sub(r"\\[a-zA-Z]+|[{}%]", " ", s).split()))
print("\nRESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
