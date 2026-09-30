import io, os, sys, warnings, yaml
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from pdf_text import extract, CACHE, SRCS
man = yaml.safe_load(io.open("manifest.yaml", encoding="utf-8"))["sources"]
from pypdf import PdfReader
os.makedirs(CACHE, exist_ok=True)
rows = []
for slug in sorted(man):
    pdf = os.path.join(SRCS, slug, "paper.pdf")
    if not os.path.exists(pdf):
        continue
    try:
        n = len(PdfReader(pdf).pages)
    except Exception:
        continue
    if n >= 50:
        rows.append((slug, n, "SKIP >=50pg"))
        continue
    out = os.path.join(CACHE, slug + ".txt")
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        rows.append((slug, n, "cached %d KB" % (os.path.getsize(out)//1024)))
        continue
    try:
        t = extract(pdf)
        io.open(out, "w", encoding="utf-8").write(t)
        rows.append((slug, n, "%d KB" % (len(t)//1024)))
    except Exception as e:
        rows.append((slug, n, "FAIL %r" % e))
for slug, n, st in sorted(rows, key=lambda r: r[1]):
    print("%-38s %4dpg  %s" % (slug, n, st))
print()
print("under 50pg: %d" % sum(1 for r in rows if "SKIP" not in r[2]))
