"""Central config for the agentic-RCA harness — the ONE place the model/provider is chosen.

Everything else (tools, degradation, trajectory logging, scoring) is provider-agnostic, so RQ
results are comparable across models by flipping RCA_PROVIDER only. Two SDK families cover all
providers: Anthropic (claude), and the OpenAI-compatible API (openai / azure / gemini / ollama —
they all speak chat.completions, only the base_url + key differ).

    RCA_PROVIDER=claude   ANTHROPIC_API_KEY=…                                   (default)
    RCA_PROVIDER=azure    AZURE_OPENAI_API_KEY=…  AZURE_OPENAI_ENDPOINT=https://<res>.openai.azure.com/openai/v1
                          RCA_MODEL=gpt-5.4            (or gpt-5.4-mini / gpt-5.4-nano)
    RCA_PROVIDER=gemini   GEMINI_API_KEY=…            RCA_MODEL=gemini-2.5-pro
    RCA_PROVIDER=openai   OPENAI_API_KEY=…  [OPENAI_BASE_URL=…]
    RCA_PROVIDER=ollama   (local; no key)             RCA_MODEL=llama3.1:8b

Never hard-code keys — they come from the environment / .env (git-ignored; see .env.example).
"""
from __future__ import annotations
import os
from dataclasses import dataclass

PROVIDER = os.environ.get("RCA_PROVIDER", "claude").lower()
MODEL = os.environ.get("RCA_MODEL", "")                       # blank -> provider default below
TEMPERATURE = float(os.environ.get("RCA_TEMPERATURE", "0"))   # 0 = reproducible (Anthropic only, see below)
MAX_TOKENS = int(os.environ.get("RCA_MAX_TOKENS", "4096"))
# GPT-5 / reasoning models reject a non-default temperature → for the OpenAI family we omit it unless
# explicitly opted in with RCA_SEND_TEMPERATURE=1.
SEND_TEMPERATURE = os.environ.get("RCA_SEND_TEMPERATURE", "0") == "1"

_DEFAULT_MODEL = {
    "claude": "claude-opus-4-8",
    "openai": "gpt-4o",
    "azure":  "gpt-5.4-mini",
    "gemini": "gemini-2.5-flash",
    "ollama": "llama3.1:8b",
}
# base_url + api-key env var per OpenAI-compatible provider (None base_url = the SDK default host)
_OPENAI_COMPAT = {
    "openai": (os.environ.get("OPENAI_BASE_URL") or None, "OPENAI_API_KEY"),
    "azure":  (os.environ.get("AZURE_OPENAI_ENDPOINT"), "AZURE_OPENAI_API_KEY"),
    "gemini": (os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"),
               "GEMINI_API_KEY"),
    "ollama": (os.environ.get("OLLAMA_URL", "http://localhost:11434/v1"), None),
}


@dataclass
class Turn:
    """Provider-neutral turn result so the trajectory logger records the same shape for any model."""
    text: str
    tool_calls: list          # [{id, name, arguments(dict)}]
    input_tokens: int
    output_tokens: int
    raw: object = None


def model_id() -> str:
    return MODEL or _DEFAULT_MODEL.get(PROVIDER, "claude-opus-4-8")


def sdk_kind() -> str:
    """'anthropic' for claude; 'openai' for the OpenAI-compatible family (openai/azure/gemini/ollama)."""
    return "anthropic" if PROVIDER == "claude" else "openai"


def make_client():
    """Construct the SDK client for the active provider (keys/urls from env). The agent loop and
    chat() both use this — so adding a provider is a one-line entry above, not new client code."""
    if PROVIDER == "claude":
        import anthropic
        return anthropic.Anthropic()                          # ANTHROPIC_API_KEY
    if PROVIDER not in _OPENAI_COMPAT:
        raise ValueError(f"unknown RCA_PROVIDER={PROVIDER!r} ({'|'.join(['claude', *_OPENAI_COMPAT])})")
    import openai
    base_url, key_var = _OPENAI_COMPAT[PROVIDER]
    api_key = os.environ.get(key_var) if key_var else "ollama"
    if not api_key:
        raise RuntimeError(f"{key_var} not set for RCA_PROVIDER={PROVIDER} (put it in .env)")
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return openai.OpenAI(**kwargs)


def openai_create_kwargs() -> dict:
    """Extra create() kwargs for the OpenAI family: max_completion_tokens (GPT-5 convention) and
    temperature only when explicitly opted in (reasoning models reject a non-default value)."""
    kw = {"max_completion_tokens": MAX_TOKENS}
    if SEND_TEMPERATURE:
        kw["temperature"] = TEMPERATURE
    return kw


# --- single-turn chat (used by the statistical baseline's narration; the agent loop drives the ---
# --- SDKs directly because tool-use threading is provider-specific — see agent.py) ---------------
def chat(system: str, messages: list, tools: list | None = None) -> Turn:
    client = make_client()
    if sdk_kind() == "anthropic":
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
    # OpenAI-compatible
    kw = dict(openai_create_kwargs())
    if tools:
        kw["tools"] = [{"type": "function", "function": t} for t in tools]
    r = client.chat.completions.create(model=model_id(),
                                       messages=[{"role": "system", "content": system}, *messages], **kw)
    m = r.choices[0].message
    calls = [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments}
             for c in (m.tool_calls or [])]
    u = r.usage
    return Turn(m.content or "", calls, getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0), raw=r)


if __name__ == "__main__":
    print(f"provider={PROVIDER} sdk={sdk_kind()} model={model_id()} "
          f"max_tokens={MAX_TOKENS} send_temp={SEND_TEMPERATURE}")
