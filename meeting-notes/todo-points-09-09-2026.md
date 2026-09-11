# Meeting 9 Sept 2026 — todo points

Present: Naser Ezzati-Jivan, Mahsa Panahandeh, Sneh Patel, Yuvraj Sehgal.
Source: `transcript-09-09-2026.txt`. Written 11 Sept 2026.

Most of this meeting was Sneh's work. Naser spoke to us for about 90 seconds at the
start, plus the publication talk. Those two parts are the whole brief for us.

---

## The short version

Naser wants **five things for every problem**. We have three. Two are missing.

| What he asked for | Where we are |
|---|---|
| Many runs of each problem, each traced | **Done.** 303 runs, 27 problems |
| An exact procedure to detect it | **Done.** Every blueprint lists its steps |
| Root cause named inside the system | **Done.** All 10 name a process, container or device |
| **Early detection** | **Not started.** We only compare whole windows, after the fact |
| **A picture per problem** | **Missing.** 10 blueprints promise a chart. Only 2 can draw one |

So the direction is right. Two gaps are real. He asked for both by name.

---

## What he said about root cause

> "Just saying that the system is under contention is not known. It's detection.
> But then what is the exact contention that's happening in the system? That's the root."

And:

> "The root cause will not be, hey, someone is bombarded. No. We'll say that, look,
> there is a file, or there is a heavy request for this specific resource."

Two rules come out of this:

- **Inside the system, not outside.** "A user is hammering us" is not a root cause.
  "This process is flooding the disk" is.
- **Detection is not root cause.** "CPU is busy" is detection. "This container's quota
  is set below what it needs" is root cause.

**We already pass this.** All 10 blueprints name something specific:

| Blueprint | What it names |
|---|---|
| cpu-contention-co-tenant | the co-tenant container |
| host-cpu-saturation | the workload that ate the CPU |
| service-cpu-throttle | the cgroup quota set too low |
| host-disk-saturation | the process flooding the device |
| service-memory-cap | the container hitting its memory limit |
| db-latency-dependency-wait | the datastore, never its callers |
| network-path-degradation | packet loss on the path |
| fork-storm | the command name of the child being spawned |
| data-exfiltration | the sending process and its destination port |
| fd-exhaustion | the process whose accept calls return EMFILE |

**One thing to check.** The blueprint *says* it names the process. We have not checked
that the verdict file actually prints the name. That is one small test, not a rewrite.

---

## What he said about pictures

> "Don't go through Trace Compass, it's going to be difficult. Use Babeltrace to just
> create some graph for each part. Then see how you can show them, like a timeline,
> resources, waiting, or sometimes it can be just a CPU usage, when CPU goes up."

This is our biggest gap. Right now:

- All 10 blueprints declare an `.svg` chart in their outputs.
- Only **2** have a script that draws one (`cpu-contention-co-tenant`,
  `db-latency-dependency-wait`).
- The other 8 promise a picture that nothing makes.

Good news: the 2 that work already use Babeltrace data and plain SVG. No new tool needed.
The work is to pull that out into one small helper and use it everywhere.

---

## Publication

| Item | Where it landed |
|---|---|
| Venue | **ICSE NIER**, for the blueprint work |
| Deadline | **23 October 2026** — six weeks from today |
| Naser's view | "Competitive. Not easy, but we can do it." |
| What is missing | **The story.** His words: "we have early results for that, right? But we need to be clear about the story." |
| Still unresolved | FSE was also named. Nobody said which one we drop. |

He also said: finish the whole thing by end of semester and it is three or four papers.

---

## Todo points

### G. New, from this meeting

- [ ] **G1. Draw a picture for every blueprint.** One helper script, used by all 10.
      Each picture shows the deciding number over time — baseline against incident.
      Babeltrace only, no Trace Compass. Copy the shape of the 2 that already work.
      *This is the clearest single ask from the meeting.*

- [ ] **G2. Add early detection.** We now compare a 60s baseline against a whole 120s
      incident window. That answers "did it happen", not "how soon could we tell".
      Cut the incident window into slices. Find the first slice where the signal crosses.
      **We can do this on data we already have** — no new collection needed.

- [ ] **G3. Check the verdict actually names the culprit.** Blueprints claim they name a
      process or container. Confirm the output file really carries the name, on a few runs.
      Small job, but it is the exact thing he defined root cause as.

- [ ] **G4. Write the NIER story in one page.** Before writing the paper. What is the new
      idea, what did we measure, why does it matter. He asked for this directly.

- [ ] **G5. Settle the venue.** NIER on 23 Oct, or FSE. Ask Naser which one we are writing.

### H. Carried over from 2 Sept — still open

- [ ] **H1. Run the with/without agent comparison on v2.** Promised as a full demo of about
      5 problems. Everything measured so far is the rule engine, not the agent.
      **This is the demo, and it is the oldest open item.**
- [ ] **H2. Build the parent/child blueprint tree.** Agreed 2 Sept. Not started.
      Fixes our worst known bug: the network blueprint was picked 0 times in 9 network runs.
- [ ] **H3. Write the small test programs.** Priority inversion, and Nagle / delayed ACK.
      Both were picked as the best cases. Neither is written.
- [ ] **H4. Start the technical report** (D1 from 2 Sept). One template per problem.
- [ ] **H5. Write the MSR abstract.** Naser has asked twice.

### I. From our own work, not the meeting

- [ ] **I1. Re-derive `service-memory-cap` against `anomaly_mem`**, or write down that the
      pair cannot be told apart.
- [ ] **I2. Write up the four faults with no signal** — `conn_pool_exhaustion`, `deadlock`,
      `resource_abuse`, `anomaly_mem`. A negative result is a result. Naser said so himself
      on 2 Sept.
- [ ] **I3. Settle the 10 Train Ticket `slow_db` / `svc_net` verdicts.**

---

## One thing going the wrong way

On 2 Sept we agreed: **latency only, kernel traces only**. Since then we added three
blueprints. Two fit. One does not:

- `fork-storm` — causes latency. Fits.
- `fd-exhaustion` — causes failed connections, not slowness. Borderline.
- `data-exfiltration` — its own blueprint says "services still answer at normal latency".
  **This is not a latency problem.**

They are good blueprints and the numbers are solid. But if the paper says "latency",
data-exfiltration does not belong in it. Two choices: widen the framing past latency, or
hold that one back. **Worth asking Naser, not deciding alone.**

---

## What was for Sneh, not us

Most of the meeting. Recorded here so we do not take on his work by accident.

- Temporal analysis — answering questions about a chosen time window.
- Critical path, and the execution graph behind it.
- The idea Naser pushed hardest: **the paths just below the critical path**. The longest
  path takes 10s and gets all the attention. The paths taking 9s are also interesting, and
  nobody has looked at them.
- Reading: Giraldeau's thesis, chapters 4 and 5. Plus the 2016 wait-analysis paper.
- Naser's push: "playing with the tool is not a challenge". Find the real research question.

**Where it touches us.** Critical path was our own open item C1–C3 from 2 Sept. Sneh is now
deep in it. Do not duplicate. Talk to him and take what is useful instead.
