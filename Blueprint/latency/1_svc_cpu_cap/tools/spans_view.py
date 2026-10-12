import json, math, sys
from collections import defaultdict
from datetime import datetime, timezone

path = sys.argv[1]
want_svc = sys.argv[2] if len(sys.argv) > 2 else None
want_kind = sys.argv[3] if len(sys.argv) > 3 else "SERVER"
BIN = 10  # seconds per slice

KINDS = {1: "INTERNAL", 2: "SERVER", 3: "CLIENT", 4: "PRODUCER", 5: "CONSUMER"}

def kind_name(k):
    if isinstance(k, str):
        return k.replace("SPAN_KIND_", "")
    return KINDS.get(k, "UNSPECIFIED")

def pct(vals, p):  # nearest-rank, vals must be sorted
    i = max(0, math.ceil(p / 100 * len(vals)) - 1)
    return vals[i]

def service_of(resource):
    for a in resource.get("attributes", []):
        if a["key"] == "service.name":
            return a["value"].get("stringValue", "?")
    return "?"

rows = []  # (service, kind, start_seconds, duration_ms)
bad = 0
with open(path) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except ValueError:
            bad += 1
            continue
        for rs in doc.get("resourceSpans", []):
            svc = service_of(rs.get("resource", {}))
            for ss in rs.get("scopeSpans", []):
                for sp in ss.get("spans", []):
                    s = int(sp["startTimeUnixNano"])
                    e = int(sp["endTimeUnixNano"])
                    rows.append((svc, kind_name(sp.get("kind")), s / 1e9, (e - s) / 1e6))

if not rows:
    sys.exit("no spans found")

t0 = min(r[2] for r in rows)
t1 = max(r[2] for r in rows)
utc = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%H:%M:%S")
print(f"spans: {len(rows)}   unreadable lines: {bad}")
print(f"first span {utc(t0)} UTC   last span {utc(t1)} UTC\n")

if want_svc is None:
    groups = defaultdict(list)
    for svc, kind, _, dur in rows:
        groups[(svc, kind)].append(dur)
    print(f"{'service':<18}{'kind':<10}{'count':>8}{'p50':>9}{'p95':>9}{'p99':>9}{'max':>9}   (ms)")
    for (svc, kind), d in sorted(groups.items()):
        d.sort()
        print(f"{svc:<18}{kind:<10}{len(d):>8}{pct(d,50):>9.1f}{pct(d,95):>9.1f}{pct(d,99):>9.1f}{d[-1]:>9.1f}")
else:
    bins = defaultdict(list)
    for svc, kind, start, dur in rows:
        if svc == want_svc and kind == want_kind:
            bins[int((start - t0) // BIN)].append(dur)
    if not bins:
        sys.exit("no spans for that service and kind")
    print(f"{want_svc} {want_kind}: one row per {BIN} s slice (ms)")
    print(f"{'offset(s)':>10}{'clock':>10}{'count':>8}{'p50':>9}{'p95':>9}{'max':>9}")
    for b in range(max(bins) + 1):
        d = sorted(bins.get(b, []))
        clock = utc(t0 + b * BIN)
        if d:
            print(f"{b*BIN:>10}{clock:>10}{len(d):>8}{pct(d,50):>9.1f}{pct(d,95):>9.1f}{d[-1]:>9.1f}")
        else:
            print(f"{b*BIN:>10}{clock:>10}{0:>8}")
