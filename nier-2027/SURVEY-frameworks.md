# Tool-output bounding in current agent frameworks

Surveyed 20 Oct 2026 from released packages (pip, --no-deps), source read, not docs.

| framework | version | bounding of model-visible tool output | class |
|---|---|---|---|
| langchain-core | 1.6.12 | `text[:max_len] + "..."` at 500 chars on serialized tool/server-tool outputs (`messages/utils.py:135-139,216-235`) | positional prefix slice |
| langchain | 1.4.6 | shell middleware truncates by LINES and BYTES with `truncated_by_*` flags + notice (`agents/middleware/shell_tool.py`) | structural-ish, labeled |
| smolagents | 1.26.0 | `content[:max//2] + notice + content[-max//2:]` at 20,000 chars on observations (`utils.py:254-265`, used `agents.py:1752`) | positional middle-deletion, labeled |
| openai-agents | 0.24.0 | prefix slice + "[truncated, N chars]" on TRACING span values only (`codex_tool.py:1253-1265`) | positional, non-model-visible |
| autogen-agentchat | 0.7.5 | none found on the tool-output path | unbounded |
| pyautogen | 0.10.0 | none found | unbounded |
| crewai | 0.11.2 | none found | unbounded |

Summary used in the paper: both general-purpose bounders found are positional
(one prefix at 500 chars, one middle-deletion at 20k); neither inspects the
structure of what it cuts; three frameworks bound nothing (deferring loss to
the window); the one structure-aware bound is a specialized shell middleware.
