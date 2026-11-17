#!/usr/bin/env python3
# net_loss.py - the degraded-network-path check: who is retransmitting, and
# whose packets are being dropped.
#
# TCP hides packet loss from the application: it just sends the lost segment
# again. So loss never shows up as an error anywhere - only as RETRANSMISSION,
# and the kernel trace records every transmit. A segment sent twice with the
# same sequence number is a retransmit.
#
# This tool reads the transmit events (net_dev_queue), which LTTng records
# with the full TCP header, and counts per flow:
#   - data segments sent (payload > 0; pure ACKs repeat their seq legitimately
#     and are NOT counted)
#   - segments sent more than once (retransmits) and the rate
# It groups flows by the sending process and container, so ONE service whose
# path is degraded stands out against everyone else's clean flows.
#
# It also counts skb_kfree (packet drop) events per container as a supporting
# signal - a lossy qdisc frees the packets it drops.
#
# Usage:
#   python3 net_loss.py <slice.txt> <slice_seconds> [min_segments]
#
#   <slice.txt>   a slice that KEEPS network events - cut it with:
#                 extract_slice.sh TRACE DAY HH:MM:SS SECS out.txt \
#                   'sched_switch|sched_waking|sched_wakeup|net_dev_queue|skb_kfree'
#   [min_segments] hide flows smaller than this (default 20)
import re
import sys
from collections import defaultdict

if len(sys.argv) < 3:
    print("usage: net_loss.py <slice.txt> <slice_seconds> [min_segments]", file=sys.stderr)
    sys.exit(1)
path, secs = sys.argv[1], float(sys.argv[2])
min_seg = int(sys.argv[3]) if len(sys.argv) > 3 else 20

re_ctx = re.compile(r'pid = (\d+), tid = \d+, procname = "([^"]*)"[^}]*net_ns = (\d+)')
re_ip = re.compile(r'saddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \], '
                   r'daddr = \[ \[0\] = (\d+), \[1\] = (\d+), \[2\] = (\d+), \[3\] = (\d+) \]')
re_len = re.compile(r'tot_len = (\d+), .*?ihl = (\d+)|ihl = (\d+), .*?tot_len = (\d+)')
re_tcp = re.compile(r'source_port = (\d+), dest_port = (\d+), seq = (\d+), ack_seq = \d+, '
                    r'data_offset = (\d+)')

# A packet crossing a veth pair or a bridge fires net_dev_queue once per
# device, so the SAME segment appears on 2-3 devices - counted naively that
# reads as a fake "50% retransmission" everywhere. So each flow is counted per
# device NAME. For one flow direction the names are distinct: the sender's own
# eth0 first, then the host-side veth of the receiver.
#
# The device must NOT be split by the context's net_ns (it was, until 17-11): the first
# copy leaves in the sender's context and the retransmit leaves from a timer in another
# one, so the two copies fell in different buckets and were never matched. Measured on
# Train Ticket: 5 runs with 4% loss on one container read 0 retransmits.
#
# Two devices also tell two kinds of retransmit apart:
#   DROPPED   - the segment is seen more often at the first device than at the next one:
#               the sender's own queue (a shaping rule, a full queue) threw a copy away.
#   SENT TWICE - both copies reached the next device: nothing was lost on the way out, the
#               ACK was late or lost (a tail-loss probe). A healthy system has these too:
#               measured 50-110 per 10 s, all toward one receiver that answers slowly.
flows = defaultdict(lambda: defaultdict(lambda: {"segs": 0, "cnt": defaultdict(int),
                                                 "senders": defaultdict(int)}))
drops = defaultdict(int)          # (procname, net_ns) -> skb_kfree count
# Who OWNS a source address. The context of a transmit event is whoever is on the CPU, not
# the socket's owner: a delayed or retransmitted segment leaves from a timer or softirq, so
# its context is swapper/N in the host namespace (measured: on a netem run every
# retransmitting flow read "swapper", and the per-container table was empty). So we vote:
# the owner of an address is the (process, net_ns) that most often sends FROM it in its own
# context, outside the host namespace.
ip_ctx = defaultdict(lambda: defaultdict(int))   # saddr -> (procname, net_ns) -> events
host_ns = set()                                  # net_ns of swapper = the host's namespace
KERNEL_CTX = ("swapper/", "ksoftirqd/", "kworker/")
n_queue = 0

with open(path, errors="replace") as f:
    for line in f:
        if ' skb_kfree:' in line:
            c = re_ctx.search(line)
            if c:
                drops[(c.group(2), c.group(3))] += 1
            continue
        if ' net_dev_queue:' not in line:
            continue
        t = re_tcp.search(line)
        ip = re_ip.search(line)
        if not t or not ip:
            continue
        n_queue += 1
        sport, dport, seq, doff = t.groups()
        c0 = re_ctx.search(line)
        if c0:
            if c0.group(2).startswith("swapper/"):
                host_ns.add(c0.group(3))
            if not c0.group(2).startswith(KERNEL_CTX):
                ip_ctx[".".join(ip.groups()[0:4])][(c0.group(2), c0.group(3))] += 1
        # payload bytes = total length - IP header - TCP header; 0 = pure ACK
        lm = re.search(r'ihl = (\d+),', line)
        tm = re.search(r'tot_len = (\d+),', line)
        if lm and tm:
            payload = int(tm.group(1)) - int(lm.group(1)) * 4 - int(doff) * 4
            if payload <= 0:
                continue
        sip = ".".join(ip.groups()[0:4])
        dip = ".".join(ip.groups()[4:8])
        key = (sip, sport, dip, dport)
        c = re_ctx.search(line)
        dv = re.search(r'len = \d+, name = "([^"]+)"', line)
        vantage = dv.group(1) if dv else "?"
        fl = flows[key][vantage]
        fl["segs"] += 1
        fl["cnt"][seq] += 1
        if c:
            fl["senders"][(c.group(2), c.group(3))] += 1

if not flows:
    print("no TCP data segments found. Either nothing was sent in this slice, or the "
          "slice has no net_dev_queue events - check how it was cut.")
    sys.exit(0)

def owner(sip):
    """(procname, net_ns) that owns this source address, or None."""
    votes = ip_ctx.get(sip)
    if not votes:
        return None
    own = {k: v for k, v in votes.items() if k[1] not in host_ns} or votes
    return max(own.items(), key=lambda kv: kv[1])[0]


def sender_of(sip, f):
    o = owner(sip)
    if o:
        return o
    return max(f["senders"].items(), key=lambda kv: kv[1])[0] if f["senders"] else ("?", "?")


# per flow: judge at the busiest device, place each retransmit with the next busiest one
best = {}
for key, devs in flows.items():
    order = sorted(devs.values(), key=lambda d: -d["segs"])
    d1 = order[0]
    d2 = order[1]["cnt"] if len(order) > 1 else None
    dup = dropped = 0
    for seq, c1 in d1["cnt"].items():
        if c1 < 2:
            continue
        dup += c1 - 1
        if d2 is not None:
            dropped += max(0, c1 - max(d2.get(seq, 0), 1))
    best[key] = {"segs": d1["segs"], "dup": dup, "senders": d1["senders"],
                 "dropped": dropped if d2 is not None else 0,
                 "twice": dup - dropped if d2 is not None else 0,
                 "unplaced": dup if d2 is None else 0}

total_segs = sum(f["segs"] for f in best.values())
total_re = sum(f["dup"] for f in best.values())
total_drop = sum(f["dropped"] for f in best.values())
total_twice = sum(f["twice"] for f in best.values())
total_unpl = sum(f["unplaced"] for f in best.values())
print(f"TCP data segments in this {secs:.0f} s slice: {total_segs} "
      f"({total_re} retransmitted, {total_re / total_segs:.1%} overall)")
print(f"  of the retransmits: {total_drop} DROPPED at the sender's own queue, {total_twice} sent "
      f"twice with both copies delivered (late or lost ACK), {total_unpl} on flows seen at one "
      "device only")
print()

# ---- per flow ---------------------------------------------------------------
print(f"Flows with the most retransmission (flows under {min_seg} segments hidden):")
print(f"  {'flow':<44}{'segs':>6}{'rexmit':>8}{'dropped':>9}{'rate':>7}  sender")
rows = [(k, f) for k, f in best.items() if f["segs"] >= min_seg]
rows.sort(key=lambda kv: (-kv[1]["dropped"], -kv[1]["dup"]))
for (sip, sp, dip, dp), f in rows[:10]:
    snd = sender_of(sip, f)
    print(f"  {sip + ':' + sp + ' -> ' + dip + ':' + dp:<44}"
          f"{f['segs']:>6}{f['dup']:>8}{f['dropped']:>9}{f['dup']/f['segs']:>7.1%}  "
          f"{snd[0]} (net_ns {snd[1]})")

# ---- per sender -------------------------------------------------------------
by_sender = defaultdict(lambda: [0, 0, 0])
for (sip, sp, dip, dp), f in best.items():
    snd = sender_of(sip, f)
    by_sender[snd][0] += f["segs"]
    by_sender[snd][1] += f["dup"]
    by_sender[snd][2] += f["dropped"]
print()
print("By sender (the process and container that own the source address):")
print(f"  {'sender':<28}{'net_ns':<14}{'segs':>7}{'rexmit':>8}{'dropped':>9}{'drop rate':>11}")
for (nm, nsid), (segs, rx, dr) in sorted(by_sender.items(), key=lambda kv: (-kv[1][2], -kv[1][1]))[:12]:
    print(f"  {nm:<28}{nsid:<14}{segs:>7}{rx:>8}{dr:>9}{(dr/segs if segs else 0):>11.1%}")

# who drops: the one-service vs host-wide question in one line
MIN_TOTAL_DROP = 3        # healthy slices measured 0 dropped segments (36 slices, two applications)
ONE_PATH_SHARE = 0.90     # one degraded path: (nearly) all drops are at one sender's queue
FEW_DROPS = 20            # under this the shares are shaky: say so
droppers = sorted(((dr, nm, nsid) for (nm, nsid), (segs, rx, dr) in by_sender.items() if dr >= 1), reverse=True)
print()
print(f"Senders whose own queue dropped segments: {len(droppers)} of {len(by_sender)}"
      + (" - " + ", ".join(f"{nm} ({nsid}) {dr}" for dr, nm, nsid in droppers[:10]) if droppers else ""))
if total_drop < MIN_TOTAL_DROP:
    print(f"  no queue drops packets here ({total_drop} dropped in all). The {total_twice} segments "
          "sent twice are not loss on the way out; a healthy system has them too")
else:
    top = droppers[0][0] / total_drop
    if top >= ONE_PATH_SHARE:
        print(f"  -> the ONE-PATH shape: {top:.0%} of all drops are at the queue of "
              f"{droppers[0][1]} (net_ns {droppers[0][2]}). That container's path is degraded")
    else:
        print(f"  -> the HOST-WIDE shape: {len(droppers)} senders drop at their own queues, the largest "
              f"holds {top:.0%} of the drops. Not one service's path")
    if total_drop < FEW_DROPS:
        print(f"     (only {total_drop} drops in {total_segs} segments - too few to trust the shares. "
              "Cut a 30 s slice and run this again; compare the segment count with the baseline, "
              "a collapse of traffic is part of the picture)")

# ---- drops ------------------------------------------------------------------
if drops:
    print()
    print("Packet frees (skb_kfree) by context - a lossy queue frees what it drops:")
    for (nm, nsid), n in sorted(drops.items(), key=lambda kv: -kv[1])[:6]:
        print(f"  {nm:<28}net_ns {nsid:<12}{n:>7}")

# ---- read it ----------------------------------------------------------------
print()
print("Read it:")
print("- DROPPED is the loss signal. A healthy system drops nothing at a sender's queue")
print("  (measured: 0 in 36 healthy slices). 'Sent twice' is NOT loss on the way out: it is")
print("  the kernel re-sending because an ACK was late, and healthy runs have 50-110 per 10 s.")
print("- ONE SERVICE'S PATH IS DEGRADED: (nearly) all drops are at ONE sender's queue.")
print("  Name that container (its net_ns). Its peers show 'sent twice' toward it, not drops.")
print("- HOST-WIDE network problem: MANY unrelated senders drop at their own queues.")
print("  That is not one service's path.")
print("- NO drops but the victim sleeps on sockets (sched S high): the peer is SLOW, not")
print("  lossy - a slow dependency or a pure-delay path. Drops prove loss; their absence")
print("  cannot rule out added delay. 'Sent twice' far above the baseline slice hints at delay.")
print("- Drops are placed by comparing two devices on the way; a flow seen at one device only")
print("  (traffic leaving the host) cannot be placed and is listed apart.")
