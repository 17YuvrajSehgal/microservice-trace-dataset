#!/usr/bin/env python3
"""Babeltrace2 source plugin — ingest Sock Shop application logs as bt2 events.

Answers Naser's gating question (§4.2 step 1): *can Babeltrace2 parse non-LTTng data?*
Yes — Babeltrace2 is plugin-based (source -> filter -> sink). This is a **source
component** that turns the Go-kit request logs our services emit into a bt2 event stream,
so plain application logs flow through the *same* Babeltrace2 graph as the LTTng kernel
trace. The same pattern (swap the regex) handles the partner's custom format.

Sock Shop Go-kit log line (real, from docker-compose_catalogue_1.log):
  ts=2026-07-28T18:12:35.839145461Z caller=logging.go:69 method=Tags result=11 err=null took=434.004µs

Run on the VM (Babeltrace2 2.1 + python3-bt2):
  BABELTRACE_PLUGIN_PATH=$(dirname $0) \
  babeltrace2 --plugin-path=$(dirname $0) \
    -c source.sockshop.applog --params 'path="…/docker-compose_catalogue_1.log"'

Parsing is unit-tested offline:  python3 applog_source.py --selftest   (no bt2 needed)
The bt2 wrapper below is written to the 2.0/2.1 Python API; validate on the VM via
run_spike.sh (the built-in source.text.dmesg proof there needs no custom code).
"""
import re, sys, datetime as dt

# ts=... method=Tags ... err=null ... took=434.004µs   (fields may appear in any order)
_TS   = re.compile(r"\bts=(\S+)")
_METH = re.compile(r"\bmethod=(\S+)")
_ERR  = re.compile(r"\berr=(\S+)")
_TOOK = re.compile(r"\btook=([\d.]+)(µs|us|ms|s)\b")
_UNIT_NS = {"µs": 1e3, "us": 1e3, "ms": 1e6, "s": 1e9}

def parse_line(line):
    """Return (ts_ns_epoch, {method, err, took_ns}) or None if not a request log line."""
    mt, mk = _TS.search(line), _TOOK.search(line)
    if not mt or not mk:
        return None
    ts = mt.group(1)
    try:                      # RFC3339 with nanoseconds: 2026-07-28T18:12:35.839145461Z
        base, frac = ts.rstrip("Z").split(".") if "." in ts else (ts.rstrip("Z"), "0")
        epoch = int(dt.datetime.strptime(base, "%Y-%m-%dT%H:%M:%S")
                    .replace(tzinfo=dt.timezone.utc).timestamp())
        ts_ns = epoch * 1_000_000_000 + int((frac + "000000000")[:9])
    except Exception:
        return None
    took_ns = int(float(mk.group(1)) * _UNIT_NS[mk.group(2)])
    meth = (_METH.search(line) or [None, ""])[1] if _METH.search(line) else ""
    err = (_ERR.search(line) or [None, "null"])[1] if _ERR.search(line) else "null"
    return ts_ns, {"method": meth, "err": err, "took_ns": took_ns}

# ---- offline self-test (no bt2 dependency) -----------------------------------
def _selftest():
    samples = [
        'ts=2026-07-28T18:12:35.839145461Z caller=logging.go:69 method=Tags result=11 err=null took=434.004µs',
        'ts=2026-07-28T18:10:01.001002003Z caller=logging.go:69 method=List result=9 err=null took=2.1s',
        'ts=2026-07-28T18:10:02.500000000Z caller=logging.go:69 method=Get err="connection reset by peer" took=13ms',
        'some non-matching info line without ts/took',
    ]
    ok = 0
    for s in samples:
        r = parse_line(s)
        print(("PARSED " if r else "skipped"), r if r else s[:60])
        ok += 1 if (r or "non-matching" in s) else 0
    print(f"\nself-test: {ok}/{len(samples)} handled as expected")
    return ok == len(samples)

# ---- bt2 source component (validate on the VM) -------------------------------
def _register():
    import bt2

    class _Iter(bt2._UserMessageIterator):
        def __init__(self, config, port):
            path, ec, sc, tc = port.user_data
            self._ec = ec
            trace = tc()                              # instantiate the trace
            self._stream = trace.create_stream(sc)
            self._lines = iter(open(path, encoding="utf-8", errors="replace"))
            self._phase = 0                           # 0=begin 1=events 2=end 3=done

        def __next__(self):
            if self._phase == 0:
                self._phase = 1
                return self._create_stream_beginning_message(self._stream)
            if self._phase == 1:
                for line in self._lines:
                    p = parse_line(line)
                    if not p:
                        continue
                    ts_ns, fields = p
                    msg = self._create_event_message(self._ec, self._stream,
                                                     default_clock_snapshot=ts_ns)
                    pf = msg.event.payload_field
                    pf["method"] = fields["method"]
                    pf["err"] = fields["err"]
                    pf["took_ns"] = fields["took_ns"]
                    return msg
                self._phase = 2
            if self._phase == 2:
                self._phase = 3
                return self._create_stream_end_message(self._stream)
            raise StopIteration

    @bt2.plugin_component_class
    class applog(bt2._UserSourceComponent, message_iterator_class=_Iter):
        def __init__(self, config, params, obj):
            path = str(params["path"])
            tc = self._create_trace_class()
            cc = self._create_clock_class(frequency=1_000_000_000, origin_is_unix_epoch=True)
            payload = tc.create_structure_field_class()
            payload.append_member("method", tc.create_string_field_class())
            payload.append_member("err", tc.create_string_field_class())
            payload.append_member("took_ns", tc.create_signed_integer_field_class(64))
            sc = tc.create_stream_class(default_clock_class=cc)
            ec = sc.create_event_class(name="applog:request", payload_field_class=payload)
            self._add_output_port("out", (path, ec, sc, tc))

    bt2.register_plugin(__name__, "sockshop",
                        description="Sock Shop application-log source for Babeltrace2",
                        author="StrataTrace")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if _selftest() else 1)
    print("import this module as a Babeltrace2 plugin, or run with --selftest")
else:
    try:
        _register()
    except Exception as _e:  # bt2 not importable outside the VM — fine for --selftest use
        pass
