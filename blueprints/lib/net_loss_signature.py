#!/usr/bin/env python3
"""Packet loss leaves fingerprints no other fault can produce. This measures them.

WHY THIS EXISTS
---------------
F13 found the endpoint view cannot separate the network faults from a healthy system or from
each other. But it was looking at latency, which every fault affects. The network recipes do
something no other fault in the catalogue does: they DROP PACKETS.

    anomaly_net  netem on EVERY container's eth0   delay 80ms  jitter 20ms  loss 2%
    svc_net      netem on ONE container's eth0     delay 150ms jitter 40ms  loss 4%

A slow datastore does not drop packets. Nor does a CPU cap, a frozen container, a memory
limit or an error storm. So loss should be specific in a way latency never is.

TWO FINGERPRINTS, both visible in our trace
-------------------------------------------
1. QUEUED BUT NEVER SENT. netem drops inside the qdisc, after net_dev_queue and before
   net_dev_xmit. Both events carry `skbaddr`, so a buffer that is queued and never transmitted
   was dropped. Reported per interface.

2. TCP RETRANSMISSIONS. A dropped segment is sent again with the same sequence number, and
   our trace carries `seq` in the TCP header. A repeated (flow, seq) is a retransmission.
   Nothing but loss causes them.

Both are reported per INTERFACE, which should also separate the two network faults from each
other: impairment on every container's veth against impairment on exactly one.

    python3 net_loss_signature.py --ctf <ctf> --gt <ground_truth> --out netloss.json
"""
from __future__ import annotations
import argparse, collections, json, os, re, subprocess, sys

# Shared reader: with CTF_CACHE_DIR set this reads a pre-extracted family file
# instead of decoding the trace again. Our own grep still runs on top either way,
# so this script sees exactly the lines it always did. See ctf_stream.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ctf_stream                                                      # noqa: E402

BT2 = os.environ.get("BT2", "/scratch/yuvraj17/bt21.sh")

TS = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{9})\]")
EVENT = re.compile(r"\] \([^)]+\) [^ ]+ (net_dev_queue|net_dev_xmit|net_if_receive_skb):")
SKB = re.compile(r"skbaddr = (0x[0-9A-Fa-f]+)")
IFACE = re.compile(r'(?<![A-Za-z])name = "([^"]*)"')   # not procname
SADDR = re.compile(r"saddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]")
DADDR = re.compile(r"daddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]")
PORTS = re.compile(r"source_port = (\d+), dest_port = (\d+)")
SEQ = re.compile(r"seq = (\d+)")
TOTLEN = re.compile(r"tot_len = (\d+)")

SEQ_MEMORY = 4096          # sequence numbers remembered per flow, oldest evicted


def secs(m):
    return (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            + int(m.group(4)) / 1e9)


def hhmmss(iso):
    return iso.split("T")[1].rstrip("Z")


def ip(m):
    return ".".join(m.group(i) for i in (1, 2, 3, 4)) if m else None


def scan(ctf, begin, end):
    p2out, _bt = ctf_stream.open_lines(ctf, begin, end,
                                      'net_dev_queue|net_dev_xmit|net_if_receive_skb', family="net")

    queued = {}                                     # skbaddr -> iface, awaiting an xmit
    queued_n = collections.Counter()
    xmit_n = collections.Counter()
    dropped_n = collections.Counter()
    seen_skb = collections.OrderedDict()            # buffers already counted once
    seen_seq = collections.defaultdict(collections.OrderedDict)   # flow -> seq -> None
    retrans = collections.Counter()                 # iface -> retransmitted segments
    segs = collections.Counter()                    # iface -> segments with a sequence number

    for line in p2out:
        me = EVENT.search(line)
        if not me:
            continue
        ev = me.group(1)
        mi, ms = IFACE.search(line), SKB.search(line)
        iface = mi.group(1) if mi else "?"

        if ev == "net_dev_queue":
            queued_n[iface] += 1
            if ms:
                queued[ms.group(1)] = iface
            continue
        if ev == "net_dev_xmit":
            xmit_n[iface] += 1
            if ms:
                queued.pop(ms.group(1), None)       # made it out; not a drop
            continue

        # net_if_receive_skb: the only place we reliably see full TCP headers both ways
        mp, mq = PORTS.search(line), SEQ.search(line)
        if not (mp and mq):
            continue
        src, dst = ip(SADDR.search(line)), ip(DADDR.search(line))
        if not (src and dst):
            continue
        mlen = TOTLEN.search(line)
        # pure ACKs carry no payload and legitimately repeat a sequence number
        if mlen and int(mlen.group(1)) <= 52:
            continue
        # the SAME packet is delivered on more than one interface (veth then bridge),
        # so without this every second sighting counts as a retransmission and every
        # run reports about 50%
        if ms:
            if ms.group(1) in seen_skb:
                continue
            seen_skb[ms.group(1)] = None
            if len(seen_skb) > 65536:
                seen_skb.popitem(last=False)
        flow = (src, int(mp.group(1)), dst, int(mp.group(2)))
        seq = int(mq.group(1))
        segs[iface] += 1
        memo = seen_seq[flow]
        if seq in memo:
            retrans[iface] += 1
        else:
            memo[seq] = None
            if len(memo) > SEQ_MEMORY:
                memo.popitem(last=False)

    ctf_stream.close_lines(_bt)

    for _skb, iface in queued.items():
        dropped_n[iface] += 1
    return queued_n, xmit_n, dropped_n, retrans, segs


def summarise(queued_n, xmit_n, dropped_n, retrans, segs, min_pkts=200):
    rows = []
    for iface in set(queued_n) | set(segs):
        q, d = queued_n.get(iface, 0), dropped_n.get(iface, 0)
        s, r = segs.get(iface, 0), retrans.get(iface, 0)
        if q < min_pkts and s < min_pkts:
            continue
        rows.append({
            "iface": iface,
            "queued": q, "transmitted": xmit_n.get(iface, 0), "never_sent": d,
            "drop_pct": round(100.0 * d / q, 3) if q else None,
            "segments": s, "retransmitted": r,
            "retrans_pct": round(100.0 * r / s, 3) if s else None,
        })
    rows.sort(key=lambda r: -(r["retrans_pct"] or 0))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctf", required=True)
    ap.add_argument("--gt", required=True)
    ap.add_argument("--out", default="netloss.json")
    ap.add_argument("--baseline-s", type=int, default=55)
    ap.add_argument("--incident-s", type=int, default=60)
    a = ap.parse_args()

    gt = json.load(open(a.gt))["fault"]
    t0 = hhmmss(gt["injection_start_utc"])

    def shift(hms, d):
        h, m, s = (int(x) for x in hms.split(":"))
        v = max(0, h * 3600 + m * 60 + s + d)       # F8: keep hour>=24, never wrap
        return f"{v//3600:02d}:{(v%3600)//60:02d}:{v%60:02d}"

    windows = {"baseline": (shift(t0, -a.baseline_s), t0),
               "incident": (t0, shift(t0, a.incident_s))}

    result = {"ctf": a.ctf, "windows": {}}
    for name, (b, e) in windows.items():
        print(f"decoding {name}: {b} -> {e} ...", flush=True)
        rows = summarise(*scan(a.ctf, b, e))
        result["windows"][name] = {"range": [b, e], "interfaces": rows}
        tot_r = sum(r["retransmitted"] for r in rows)
        tot_s = sum(r["segments"] for r in rows)
        print(f"  {len(rows)} interfaces, {tot_r} retransmits of {tot_s} segments "
              f"({100.0 * tot_r / max(tot_s, 1):.3f}%)")

    base = {r["iface"]: r for r in result["windows"]["baseline"]["interfaces"]}
    inc = {r["iface"]: r for r in result["windows"]["incident"]["interfaces"]}

    comparison = []
    for iface in sorted(set(base) & set(inc)):
        bb, ii = base[iface], inc[iface]
        comparison.append({
            "iface": iface,
            "retrans_pct_baseline": bb["retrans_pct"], "retrans_pct_incident": ii["retrans_pct"],
            "drop_pct_baseline": bb["drop_pct"], "drop_pct_incident": ii["drop_pct"],
            "segments_incident": ii["segments"], "queued_incident": ii["queued"],
        })
    comparison.sort(key=lambda r: -(r["retrans_pct_incident"] or 0))
    result["comparison"] = comparison

    # HOW MANY interfaces are impaired is what should separate the two network faults:
    # every container's veth against exactly one.
    hit = [r for r in comparison
           if (r["retrans_pct_incident"] or 0) >= 0.5
           and (r["retrans_pct_incident"] or 0) >= 3 * ((r["retrans_pct_baseline"] or 0) + 0.05)]
    result["signature"] = {
        "n_interfaces": len(comparison),
        "n_impaired": len(hit),
        "impaired_ifaces": [r["iface"] for r in hit][:10],
        "worst_retrans_pct": max([(r["retrans_pct_incident"] or 0) for r in comparison],
                                 default=None),
        "median_retrans_pct_baseline": (
            sorted(v)[len(v) // 2] if (v := [(r["retrans_pct_baseline"] or 0)
                                             for r in comparison]) else None),
        "worst_drop_pct": max([(r["drop_pct_incident"] or 0) for r in comparison], default=None),
    }

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(result, open(a.out, "w"), indent=2)
    print(f"\nwrote {a.out}\n")
    print(f"{'interface':20s} {'retrans b%':>11s} {'retrans i%':>11s} "
          f"{'drop b%':>9s} {'drop i%':>9s} {'segs':>8s}")
    for r in comparison[:14]:
        print(f"{r['iface'][:20]:20s} {str(r['retrans_pct_baseline']):>11s} "
              f"{str(r['retrans_pct_incident']):>11s} {str(r['drop_pct_baseline']):>9s} "
              f"{str(r['drop_pct_incident']):>9s} {r['segments_incident']:8d}")
    s = result["signature"]
    print(f"\n{s['n_impaired']} of {s['n_interfaces']} interfaces impaired "
          f"{s['impaired_ifaces']}; worst retransmit {s['worst_retrans_pct']}%, "
          f"baseline median {s['median_retrans_pct_baseline']}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
