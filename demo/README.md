# Ciena meeting pack — 24 September 2026

| file | what it is |
|---|---|
| `ciena-talk-plan.md` | running order, talking points, expected questions, what not to say |
| `ciena-brief.md` | one page they can read in two minutes |
| `ciena-results.html` | the shareable results page (published as an artifact) |
| `demo-transcript.jsonl` | the recorded agent run the demo replays — self-contained |
| `chart-blueprint-effect.png` | figure used by the results page |

## The demo

```
python blueprints/lib/demo_agent.py --step     # press Enter between sections
python blueprints/lib/demo_agent.py --pace 0   # rehearse, no pauses
```

**It replays a recording.** No network, no cluster, no API key — it cannot fail in the room.
The recorded run is the `nohint` condition: the agent was not told an incident happened, when
it was, or where to look. It named the right container and hit the window at IoU 0.926.

To run the real agent instead, on the cluster:

```
python blueprints/lib/demo_agent.py --live /scratch/.../dataset/runs/sockshop/svc_net/<run>
```

Only do that with a known-good connection. The agent succeeds on this problem about a third of
the time, so a live run may honestly fail — which is fine to show, but decide that in advance
rather than discovering it in front of people.
