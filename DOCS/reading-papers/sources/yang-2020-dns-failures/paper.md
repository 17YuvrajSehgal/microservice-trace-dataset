# Paper Context: A Deep Dive into DNS Query Failures (USENIX ATC 2020)

> Purpose of this file: a complete, faithful reference for an AI coding/research agent.
> Our blueprint 11 (`dns-delay`) cites this for one thing: **DNS failure is common in the
> wild (13.5%)**. That claim is sound. Everything else in the paper is about the public
> Internet, not microservices, and §9 explains why almost none of it transfers.

---

## 1. Bibliographic info

- **Title:** A Deep Dive into DNS Query Failures
- **Authors:** Donghui Yang (ICT-CAS, UCAS), Zhenyu Li (ICT-CAS, UCAS, Purple Mountain
  Laboratories), Gareth Tyson (Queen Mary University of London)
- **Venue:** 2020 USENIX Annual Technical Conference (ATC '20), 15-17 July 2020, pp. 507-...
- **Open access:** https://www.usenix.org/conference/atc20/presentation/yang
- **ISBN:** 978-1-939133-14-4

```bibtex
@inproceedings{yang2020dns,
  title     = {A Deep Dive into {DNS} Query Failures},
  author    = {Yang, Donghui and Li, Zhenyu and Tyson, Gareth},
  booktitle = {2020 USENIX Annual Technical Conference (USENIX ATC 20)},
  pages     = {507--518}, year = {2020}
}
```

---

## 2. One-paragraph summary

The authors study **3 billion DNS queries** from deep-packet-inspection appliances at three
Chinese ISPs, and ask a question most DNS papers skip: how often do lookups **fail**, and why.
The headline is **13.5% of queries fail**. The failures are not spread evenly. IPv6 lookups
(AAAA) fail **64.2%** of the time against **6.9%** for IPv4 (A), largely because around 60% of
domains have no AAAA record at all. A small number of domains cause most failures, and many of
those are malicious. Resolvers differ a lot, and new generic TLDs fail about 10 percentage
points more often than established ones.

---

## 3. Why the paper exists

- DNS is a hard dependency for nearly everything. When it fails, services that are perfectly
  healthy become unreachable. Their example: the **2016 Dyn DDoS**, which broke lookups for
  Netflix and Visa while those services were still online.
- Prior work looked at root servers, at NXDOMAIN responses, and at using NXDOMAIN to detect
  botnets.
- **This paper deliberately excludes NXDOMAINs** - it is about failures caused by DNS
  *infrastructure*, not by typos or domains that do not exist.

---

## 4. Dataset

- **Passive DNS logs** from DPI appliances at **3 ISPs in China**. Each appliance parses the
  DNS *response* from recursive resolver to end user.
- Each log has: anonymised user IP, BGP prefix, ASN, resolver IP, query type, all resource
  records, a timestamp in seconds, and whether resolver and user share a /24.
- **14 samples**, every other day in **February 2018**. Each sample is a **10-minute** window
  across all appliances.
- **3,085,998,589 logs** total.
- CNAME responses are followed to the final record.
- **No IPv6 addresses** appear among end users or resolvers - only inside AAAA answers.

### How they identify a failure

They check whether a response contains a valid answer of the requested type. They have **no
response code** in the data, so NXDOMAINs are removed by a heuristic: **drop every domain that
never succeeded even once anywhere in the dataset**.

After filtering: **2,811,010,890 logs**, from **37,070,965 unique IPs**, to **246,991
resolvers**.

### Caveats the authors state themselves

1. The heuristic keeps domains that were resolvable earlier and became NXDOMAIN later.
2. **Failures that produce no response at all (packet loss) are invisible.** The data is
   response-derived.
3. A valid DNS response does not mean the server behind it is alive.
4. DNS manipulation and on-path interception can produce wrong mappings they cannot detect.
5. They checked that censored domains still return valid addresses, so censorship is not
   silently inflating failures.
6. **The data is local to China.** They argue DNS is globally distributed so infrastructure
   findings should generalise.

**Ethics:** ISPs collect these logs for service quality and security; user IPs were anonymised
with Crypto-PAn; users are notified on subscription that logs may be shared with academics; no
new collection was triggered.

---

## 5. The headline numbers

### Overall (Table 1)

| Query type | Share of queries | Success rate |
|---|---|---|
| **A** (IPv4) | **86.2%** | **93.1%** |
| **AAAA** (IPv6) | **10.4%** | **35.8%** |
| PTR | 2.8% | 40.4% |
| MX | 0.1% | 82.9% |

**13.5% of all queries fail.** A-record failure is 6.9%; **AAAA failure is 64.2%**, which they
note is nearly **3× the 2012 figure**.

### Across domains

- **A queries:** 93.7% of domains succeed over 95% of the time. Filtering to domains with at
  least 100 requests, 84.9% still exceed 95% - but **7% of domains succeed less than half the
  time**.
- **AAAA queries:** only 34.3% of domains exceed 95%. Among domains with 100+ queries, only
  **7.8%** exceed 95%, and **about 60% of domains were never successfully resolved at all**.
- Failures are **heavy-tailed**: a handful of domains cause most of them.
- **20% of local resolvers have never successfully resolved a single AAAA query** - they are
  not IPv6-ready.

### By domain category (Figure 3)

Top categories by failure rate: Proxy (99.0%), **Education (88.4%)**, P2P (87.9%), Religion
(31.3%), Hunting (30.5%), Porn (27.7%), Auctions (27.2%), Info (24.6%), Parked (21.6%).

Proxy, porn and parked are unsurprising. **Education at second place is not** - it traces to
one domain, `clock.cuhk.edu.hk`, the third most-failed domain overall. In 8 of the 11
categories, **the top 3 second-level domains account for over 80% of failures**.

### TLDs and malice

- New gTLDs and internationalised domain names succeed about **10 percentage points less**
  than established domains, mostly because of malicious domains.
- Certain ASes concentrate malicious new-gTLD hosting; those domains are **73.7% of all new
  gTLD queries**.
- The malicious domains are volatile - **none were resolvable by the time of writing**.

---

## 6. What causes the AAAA failures

The paper is careful here. High AAAA failure is partly **expected behaviour**, not breakage:

- **Happy Eyeballs** (RFC) makes clients issue A and AAAA in parallel and use whichever answers
  usefully. An unanswered AAAA is not a user-visible error.
- **~60% of domains simply have no AAAA record.** Asking for one that does not exist is a
  failure by their metric but is correct DNS behaviour.

So "64.2% of AAAA queries fail" is a true statement about query outcomes and a misleading
statement about DNS health, unless both causes are named.

---

## 7. What kind of paper this is

- **Measurement study.** No system, no tool, no detection method, no mitigation evaluated.
- The "system implications" it proposes are recommendations, not implemented or tested.
- Everything is **recursive-resolver-to-client** traffic on the public Internet.
- It is a **10-minute-window sample** repeated 14 times, not continuous monitoring.

---

## 8. What this means for our work

**The one safe citation, and it is the one we use.** Blueprint 11 cites this for *"13.5% of
DNS queries fail in the wild, so DNS failure is common"*. That is exactly what the paper
measures, on the largest dataset of its kind. Good citation, correctly used.

**Everything else does not transfer, and we should say so.** The reference pack already flags
this - *"there is no MSR-style study of DNS incidents in microservices; ATC 2020 is about
queries on the Internet"* - and reading the paper confirms it is the right caveat:

| This paper | Our setting |
|---|---|
| public Internet, 3 Chinese ISPs | one host, containers on a Docker network |
| recursive resolvers, 246,991 of them | one embedded Docker DNS resolver |
| failures dominated by malicious and parked domains | internal service names only |
| A vs AAAA support across the whole domain space | a fixed, small set of container names |
| failure = no valid answer returned | our fault is **delay**, not failure |

**The most important mismatch:** our `dns_delay` fault injects **latency**, and the service
then resolves normally. This paper measures **failures**, and explicitly cannot see queries
that produced no response. So it does not describe our fault at all - it describes why DNS is
worth worrying about in general.

**Two details that are genuinely relevant to blueprint 11.**

- **Happy Eyeballs / parallel A + AAAA.** This paper confirms the mechanism exists at scale
  and that AAAA is frequently unanswered. Our blueprint's signature is a ~5 s pause between a
  DNS send and the next one, and the parallel A/AAAA pair is part of that story (the Pumputis
  post is the better citation for the 5 s timeout itself).
- **Their blind spot is our signal.** They cannot see queries that got no response, because
  their data is built from responses. A kernel trace sees the `sendto` with no matching reply,
  which is precisely the timing gap our blueprint looks for. That is a small but real argument
  for the kernel view.

---

## 9. Safe claims

- 13.5% of DNS queries fail in the wild, measured over 3 billion queries.
- A-record queries are 86.2% of traffic and fail 6.9% of the time; AAAA queries are 10.4% and
  fail 64.2%.
- About 60% of domains have no AAAA support; 20% of local resolvers never successfully
  resolved an AAAA query.
- Failures are heavy-tailed - a small number of domains cause most of them, and in 8 of 11
  categories the top 3 SLDs account for over 80%.
- New gTLDs and IDNs have roughly 10 percentage points lower success, driven by malicious
  domains.
- glibc-style clients issue A and AAAA in parallel (Happy Eyeballs), so an unanswered AAAA is
  often not user-visible.
- The 2016 Dyn DDoS made Netflix and Visa unreachable while those services were still running.

## 10. Do NOT claim

- That this says anything about DNS **latency**. It measures failure, not delay.
- That it covers microservices, containers, or Kubernetes. It is ISP-level Internet traffic.
- That 64.2% AAAA failure indicates broken infrastructure. Most of it is domains with no AAAA
  record, plus Happy Eyeballs working as designed.
- That it captures all failures. Queries with no response at all are invisible to the dataset.
- That the failure rates are global. The data is from three Chinese ISPs over 14 ten-minute
  windows in February 2018.

## 11. Reusable ideas

- **Filter the trivial explanation before measuring the interesting one.** They removed
  NXDOMAINs so that what remained was infrastructure failure. Our equivalent is separating
  "the check did not apply" from "the check found nothing".
- **Report the heavy tail, not the mean.** A 13.5% average hides that a handful of domains
  cause most of it.
- **Name the benign cause of an alarming number.** They could have led with "64% of IPv6
  lookups fail" and instead explained that most of it is missing AAAA records and Happy
  Eyeballs.
- **State the blind spot in the data.** "We cannot see queries that produced no response" is
  exactly the kind of sentence our own dataset documentation should contain.
