# When a blueprint makes an agent worse

Measured 22 September 2026 on 600 runs across two applications.

A blueprint made the agent **worse** at one task, consistently, on both applications. Chasing
that produced a mistake of mine and, underneath it, a result worth reporting.

## The observation

On `anomaly_net`, the agent given the blueprint found the incident window far less often than
the agent given nothing. It did not answer wrongly - it answered `unknown`.

| | without blueprint | with blueprint |
|---|---|---|
| abstained, Sock Shop | 1 of 30 | **14 of 30** |
| abstained, Train Ticket | 9 of 30 | **23 of 30** |

Both applications, same direction, same size.

## The first explanation was wrong

The agent's own words pointed at a line in our base method:

> A step present in everything usually means the workload changed rather than the system
> misbehaving.

That is sound for a co-tenant and backwards for a host-wide network fault, where every series
drops together **because** the machine is degraded. The agent quoted the rule while abstaining.

So we rewrote it and re-ran all 360 Sock Shop cells.

**It made no difference.** Abstentions went 14/30 to 13/30; the gap stayed at +13. It also cost
`noisy_neighbor` five points. Quoting a rule is not the same as being bound by it.

## The real cause, first part: we told the agent a falsehood

The network blueprint's deciding check is TCP retransmission rate. The kernel recipe we wrote
for it said:

> There is no TCP retransmission tracepoint in this profile, so a retransmission RATE is not
> measurable.

That is false. Every packet event in these traces carries the full TCP header:

```
net_if_receive_skb: ... transport_header = { source_port = 8079  dest_port = 46922
                                             seq = 148521618  ack_seq = 3861148859 ... }
```

A sequence number repeating on one flow **is** a retransmission - which is exactly how the
campaign measured 51.9-61.8% retransmission from these same traces in September. The sentence
was written from the general fact that `tcp_retransmit_skb` does not exist, without checking
what this profile captures.

The agent was told its deciding check was impossible and honestly refused to conclude. **It
behaved correctly on a false premise.**

## Correcting it helped, and did not fix it

| | Sock Shop | Train Ticket |
|---|---|---|
| gap with the false recipe | +13 | +14 |
| gap with the true recipe | **+8** | **+8** |

Both applications land on exactly +8. Train Ticket's given-arm hits went 1 to 6.

So roughly a third of the damage was our false sentence. The rest is something else, and it is
the same size on both applications - which is what you would expect if it comes from the
blueprint rather than from either codebase.

## The real cause, second part - and this is the finding

The blueprint's discriminator is a **threshold on a rate**:

> at least one interface retransmits heavily - measured 18.5% to 60.7%

The corrected recipe now says, truthfully, that the agent can show retransmission **is or is
not happening** but cannot compute a **rate**: `ctf_lines` returns at most 40 raw lines over a
narrow range.

So the agent can see the signal and still cannot satisfy the check as written. It needs a
percentage to compare against the cut, can only obtain a yes or no, and abstains.

> **A blueprint whose deciding check is a threshold on a quantity the deployed tools cannot
> compute will make an agent abstain - even when the underlying signal is plainly visible.**

That is a sharper and more useful claim than "blueprints can hurt". It is about portability: a
blueprint authored where a rate was computable, deployed where it is not, silently converts a
capable agent into one that refuses to answer.

## What to do about it

**Every thresholded discriminator needs a qualitative fallback.** Here the fallback is easy and
true: *retransmission present at all, against a baseline of none*. That is what the campaign
actually measured, it is what `ctf_lines` can show, and it decides the same question.

**A blueprint should state which of its checks are unreachable in the current deployment**, and
say what to conclude without them - rather than leaving the agent to discover the gap and stop.

**And the evidence-first rule applies to the recipes, not only the discriminators.** The
validator rejects a discriminator with no measurement behind it. The kernel recipes had no such
check, and that is where the false sentence lived - in the very file that enforces the rule on
everything else.

## Reproducing

| directory | condition |
|---|---|
| `results/q2-full` | old prompt, false recipe |
| `results/q2-ss2` | new prompt, false recipe (isolates the prompt) |
| `results/q2-net-ss`, `results/q2-net-tt` | new prompt, true recipe (isolates the recipe) |

Each is 60 `anomaly_net` cells per application, 3 incidents x 2 arms x 2 asks x 5 repeats.
