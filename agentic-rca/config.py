"""Central config for the agentic-RCA harness — the ONE place the model/provider is chosen.

The RCA agent never imports a vendor SDK directly; it calls `chat()` from here. Swapping the
model is therefore a config change, not a code change:

    default:                       Claude (Anthropic)         — set ANTHROPIC_API_KEY
    RCA_PROVIDER=openai            GPT-4o / o-series           — pip install openai, set OPENAI_API_KEY
    RCA_PROVIDER=ollama            local Llama/Qwen/etc.       — ollama serve (no key)

Everything else in the harness (tools, degradation, trajectory logging, scoring) is
provider-agnostic, so RQ results are comparable across models by flipping RCA_PROVIDER only.
"""
from __future__ import annotations
import os
from dataclasses import dataclass

# --- what the harness reads everywhere ------------------------------------------------------
PROVIDER = os.environ.get("RCA_PROVIDER", "claude").lower()
MODEL = os.environ.get("RCA_MODEL", "")          # blank -> provider default below
TEMPERATURE = float(os.environ.get("RCA_TEMPERATURE", "0"))   # 0 = reproducible for the study
MAX_TOKENS = int(os.environ.get("RCA_MAX_TOKENS", "4096"))

_DEFAULT_MODEL = {
    "claude": "claude-opus-4-8",          # latest Claude; override with RCA_MODEL=claude-sonnet-5 etc.
    "openai": "gpt-4o",
    "ollama": "llama3.1:8b",
}


@dataclass
class Turn:
    """One agent turn's result — provider-neutral so the trajectory logger records the same
    shape regardless of model: text, any tool calls requested, and token usage (RQ2/RQ4 cost)."""
    text: str
    tool_calls: list          # [{id, name, arguments(dict)}]
    input_tokens: int
    output_tokens: int
    raw: object = None        # the underlying provider response, if a caller needs it


def model_id() -> str:
    return MODEL or _DEFAULT_MODEL.get(PROVIDER, "claude-opus-4-8")


def chat(system: str, messages: list, tools: list | None = None) -> Turn:
    """Single provider-agnostic chat call. `tools` are JSON-schema tool specs (OpenAI-style
    {name, description, parameters}); each provider adapter maps them to its native format.
    Returns a Turn. This is the ONLY function the agent loop calls to reach a model."""
    if PROVIDER == "claude":
        return _chat_claude(system, messages, tools)
    if PROVIDER == "openai":
        return _chat_openai(system, messages, tools)
    if PROVIDER == "ollama":
        return _chat_ollama(system, messages, tools)
    raise ValueError(f"unknown RCA_PROVIDER={PROVIDER!r} (claude|openai|ollama)")


# --- adapters: the ONLY per-provider code. Adding a model = adding one of these. -------------
def _chat_claude(system, messages, tools) -> Turn:
    import anthropic
    client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY
    kw = {}
    if tools:
        kw["tools"] = [{"name": t["name"], "description": t.get("description", ""),
                        "input_schema": t["parameters"]} for t in tools]
    r = client.messages.create(model=model_id(), max_tokens=MAX_TOKENS,
                               temperature=TEMPERATURE, system=system, messages=messages, **kw)
    text = "".join(b.text for b in r.content if b.type == "text")
    calls = [{"id": b.id, "name": b.name, "arguments": b.input}
             for b in r.content if b.type == "tool_use"]
    return Turn(text, calls, r.usage.input_tokens, r.usage.output_tokens, raw=r)


def _chat_openai(system, messages, tools) -> Turn:
    from openai import OpenAI
    client = OpenAI()   # reads OPENAI_API_KEY
    kw = {}
    if tools:
        kw["tools"] = [{"type": "function", "function": t} for t in tools]
    r = client.chat.completions.create(model=model_id(), temperature=TEMPERATURE,
                                        max_tokens=MAX_TOKENS,
                                        messages=[{"role": "system", "content": system}, *messages], **kw)
    m = r.choices[0].message
    calls = [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments}
             for c in (m.tool_calls or [])]
    return Turn(m.content or "", calls, r.usage.prompt_tokens, r.usage.completion_tokens, raw=r)


def _chat_ollama(system, messages, tools) -> Turn:
    import json, urllib.request
    body = {"model": model_id(), "stream": False, "options": {"temperature": TEMPERATURE},
            "messages": [{"role": "system", "content": system}, *messages]}
    if tools:
        body["tools"] = [{"type": "function", "function": t} for t in tools]
    req = urllib.request.Request(os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat"),
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req))
    msg = r.get("message", {})
    calls = [{"id": str(i), "name": c["function"]["name"], "arguments": c["function"].get("arguments", {})}
             for i, c in enumerate(msg.get("tool_calls", []) or [])]
    return Turn(msg.get("content", ""), calls,
                r.get("prompt_eval_count", 0), r.get("eval_count", 0), raw=r)


if __name__ == "__main__":
    print(f"provider={PROVIDER} model={model_id()} temp={TEMPERATURE} max_tokens={MAX_TOKENS}")
