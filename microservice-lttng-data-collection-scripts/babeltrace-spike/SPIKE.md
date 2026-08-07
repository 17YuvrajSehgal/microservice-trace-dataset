# Spike — can Babeltrace2 parse non-LTTng data? (§4.2 gating question)

**Short answer: yes.** Babeltrace2 is a plugin-based graph — **source → filter → sink**,
the same shape as OpenTelemetry. Anything you can write a *source component* for flows
through the same graph as the LTTng kernel trace. Two levels of evidence:

1. **Built-in, no code — proves non-CTF text ingestion today.** Babeltrace2 ships
   `source.text.dmesg`, which parses plain-text Linux kernel logs (a non-LTTng, non-CTF
   text format) into a bt2 event stream. `run_spike.sh` runs this against a real `dmesg`
   dump. If it emits events, the gating question is answered empirically.

2. **Custom formats (our app logs + the partner format) — a small source component.**
   `applog_source.py` here is a Babeltrace2 **source component** that turns our Sock Shop
   Go-kit request logs into `applog:request` events (`method`, `err`, `took_ns`). The same
   pattern — swap the regex in `parse_line()` — ingests the partner's custom format that
   Trace Compass can't read. Its *parsing* is unit-tested offline
   (`python3 applog_source.py --selftest` → 4/4); the bt2 wrapper is validated on the VM.

**Why it matters:** this makes Babeltrace2 the **one unified backend** for all four
modalities — kernel CTF (`source.ctf.fs`), application logs (custom source above), and
later OTel/metrics sources — all in a single graph the MCP layer sits on top of. That is
exactly the §4.2 goal.

---

## Run it on the VM (`babeltrace-spike/run_spike.sh`)

```bash
gcloud compute instances start stratatrace-collector --zone=us-east1-d
gcloud compute ssh stratatrace-collector --zone=us-east1-d
cd ~/microservice-trace-dataset && git pull
bash microservice-lttng-data-collection-scripts/babeltrace-spike/run_spike.sh
```

It runs, in order:
1. `babeltrace2 --version` + `list-plugins` — confirms the `ctf`, `text`, `utils`,
   `lttng-utils` plugins are present.
2. **Built-in proof:** `babeltrace2 <dmesg.txt> -c source.text.dmesg | head` — plain text
   in, bt2 events out (no custom code).
3. **Custom proof:** `python3 applog_source.py --selftest`, then run the plugin over a real
   `docker-compose_catalogue_1.log` from the dataset → `applog:request` events.

**Prereq for step 3:** the Python bt2 bindings (`python3-bt2`, ships with the
`babeltrace2` apt package on Ubuntu 24.04). Steps 1–2 need only the `babeltrace2` CLI, which
is already installed.

## Status
- Parsing logic: **verified offline** (selftest 4/4).
- Built-in `source.text.dmesg` non-CTF proof: **ready to run** (guaranteed by the built-in
  component; VM was stopped, so not yet executed this session).
- Custom `applog_source.py` bt2 wrapper: **written, pending VM validation** (2.0/2.1 Python
  API — expect at most minor field-API tweaks; `run_spike.sh` will surface them).

## Next (once validated)
- Add a `source.ctf.fs` + `source.sockshop.applog` graph so kernel + app-logs stream
  together, and a trivial sink that prints a unified timeline — the "one backend" demo.
- Point the MCP layer's raw-access / query tools at that graph (§4.2 step 2).
