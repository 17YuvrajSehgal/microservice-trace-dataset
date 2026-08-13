#!/usr/bin/env python3
"""Full-fidelity agent transcript capture — the publishable record of every agent diagnosis.

Results tables alone are not auditable: for the paper artifact we persist, per
(incident x condition), EXACTLY what the model was given and what it produced —
the system prompt, the tool schemas, every raw API response (all content blocks:
text, thinking/reasoning, tool calls; plus usage, response ids, fingerprints), and
every tool execution (full untruncated result AND precisely what was sent to the
model). Ground truth is deliberately NOT in a transcript: the file itself is the
proof the agent never saw the label.

Recording is logging-only — it changes neither the messages nor the API kwargs,
so transcribed results stay comparable with earlier (untranscribed) runs.

File layout: one JSON per diagnosis — {"meta": …, "events": [ordered], "final": …}.
Schema and guarantees are documented in TRANSCRIPTS.md; bundle for sharing with
bundle_artifact.py.
"""
from __future__ import annotations
import hashlib
import json
import os
import platform
import subprocess
from datetime import datetime, timezone

SCHEMA_VERSION = 1


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return None


def to_jsonable(o):
    """Best-effort lossless serialization of SDK objects (pydantic model_dump first,
    then containers, then str). Used on raw API responses so nothing is dropped."""
    if o is None or isinstance(o, (bool, int, float, str)):
        return o
    if isinstance(o, (list, tuple)):
        return [to_jsonable(x) for x in o]
    if isinstance(o, dict):
        return {str(k): to_jsonable(v) for k, v in o.items()}
    for m in ("model_dump", "to_dict"):
        f = getattr(o, m, None)
        if callable(f):
            try:
                return to_jsonable(f())
            except Exception:
                pass
    return str(o)


class Transcript:
    """Ordered event log for ONE agent diagnosis. Events (in conversation order):
      system_prompt / tools_schema / user_message   — the exact inputs, once
      api_response                                  — one per API call, raw response dump
      tool_execution                                — full result + what was sent to the model
      error                                         — captured exception, if any
    finalize() stamps the diagnosis, stop reason and totals; write() is atomic."""

    def __init__(self, run_id: str, method: str = "agent", condition: str | None = None,
                 extra: dict | None = None):
        import config
        temp = (config.TEMPERATURE
                if (config.sdk_kind() == "anthropic" or config.SEND_TEMPERATURE)
                else "omitted")
        self.meta = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "condition": condition,
            "method": method,
            "provider": config.PROVIDER,
            "model": config.model_id(),
            "sdk": config.sdk_kind(),
            "request_kwargs": {"max_tokens": config.MAX_TOKENS, "temperature": temp},
            "stratatrace_app": os.environ.get("STRATATRACE_APP"),
            "git_commit": git_commit(),
            "python": platform.python_version(),
            "host": platform.node(),
            "started_utc": _utc(),
        }
        if extra:
            self.meta.update(extra)
        self.events: list[dict] = []
        self.final: dict = {}

    def event(self, etype: str, **fields):
        self.events.append({"i": len(self.events), "t": _utc(), "type": etype, **fields})

    def count(self, etype: str) -> int:
        return sum(1 for e in self.events if e["type"] == etype)

    def finalize(self, diagnosis: dict | None, stop_reason: str, **totals):
        self.meta["finished_utc"] = _utc()
        self.final = {"diagnosis": diagnosis, "stop_reason": stop_reason,
                      "n_api_calls": self.count("api_response"), **totals}

    def write(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"meta": self.meta, "events": self.events, "final": self.final},
                      f, indent=1, default=str)
        os.replace(tmp, path)
