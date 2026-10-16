#!/usr/bin/env python3
"""query_source — the agent's source-code context (v4; new_design.md §3.3, first retrieval source).

Claude-Code-style ergonomics in one tool, three ops:
    find_files  glob-style file discovery      ("**/*Order*Impl.java", "seat*.js")
    search      regex/text content search      -> file:line: matched line (capped)
    read        numbered window of one file    -> like `cat -n`, offset/limit

Corpus = the application's own repository (submodules in this repo), resolved per app:
    trainticket -> train-ticket/        (Java monorepo, all ts-* services)
    sockshop    -> microservices-demo/  (deployment meta-repo; service source varies)
Override with RCA_SOURCE_ROOT. Missing corpus -> a clean note, never an error.

Leakage: source code is static per app and fault-agnostic — it names real services
(the answer space) but cannot encode which fault was injected into a given run.
bytes_touched counts bytes actually scanned/read (the honest cost of index-free search).
"""
from __future__ import annotations
import fnmatch
import os
import re
from functools import lru_cache

_APP_DIRS = {"trainticket": "train-ticket", "sockshop": "microservices-demo"}
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SKIP_DIRS = {".git", ".github", ".idea", ".mvn", "__pycache__", "node_modules", "target",
              "build", "dist", "out", "vendor", ".gradle", "coverage", "old-docs"}
_SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".pdf", ".jar", ".class",
             ".zip", ".gz", ".tar", ".war", ".woff", ".woff2", ".ttf", ".eot", ".map",
             ".lock", ".bin", ".exe", ".so", ".dylib", ".mp4", ".db"}
_MAX_FILE_BYTES = 256 * 1024          # search skips larger files (build artifacts, dumps)
_MAX_FIND = 50
_MAX_MATCHES = 40
_READ_DEFAULT = 120
_READ_MAX = 400


def source_root(app: str | None) -> str | None:
    override = os.environ.get("RCA_SOURCE_ROOT")
    if override:
        return override if os.path.isdir(override) else None
    d = _APP_DIRS.get((app or os.environ.get("STRATATRACE_APP") or "").lower())
    if not d:
        return None
    p = os.path.join(_REPO_ROOT, d)
    # an un-initialized submodule is an empty dir — treat as absent
    return p if os.path.isdir(p) and any(os.scandir(p)) else None


@lru_cache(maxsize=4)
def _walk(root: str) -> tuple:
    """All searchable files under root as (relpath, size), pruned + cached."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for f in filenames:
            if os.path.splitext(f)[1].lower() in _SKIP_EXT or f.endswith(".min.js"):
                continue
            p = os.path.join(dirpath, f)
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            out.append((os.path.relpath(p, root).replace(os.sep, "/"), size))
    return tuple(sorted(out))


def _match(rel: str, pattern: str) -> bool:
    pat = pattern.replace("\\", "/")
    if "/" in pat:
        # '**/' prefix means "any depth" — also allow matching from the root
        return fnmatch.fnmatch(rel, pat) or (pat.startswith("**/") and fnmatch.fnmatch(rel, pat[3:]))
    return fnmatch.fnmatch(os.path.basename(rel), pat)


def find_files(root: str, pattern: str):
    hits = [(rel, size) for rel, size in _walk(root) if _match(rel, pattern)]
    res = {"files": [{"path": rel, "bytes": size} for rel, size in hits[:_MAX_FIND]]}
    if len(hits) > _MAX_FIND:
        res["note"] = f"{len(hits) - _MAX_FIND} more matches omitted — narrow the pattern"
    if not hits:
        res["note"] = "no files match; try a broader pattern like '**/*name*'"
    return res, 0


def search(root: str, query: str, path_filter: str | None = None):
    try:
        rx = re.compile(query, re.IGNORECASE)
    except re.error:
        rx = re.compile(re.escape(query), re.IGNORECASE)
    matches, scanned, truncated = [], 0, False
    for rel, size in _walk(root):
        if size > _MAX_FILE_BYTES:
            continue
        if path_filter and not _match(rel, path_filter):
            continue
        try:
            with open(os.path.join(root, rel), "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        scanned += len(text)
        if "\x00" in text[:1024]:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                matches.append({"file": rel, "line": i, "text": line.strip()[:160]})
                if len(matches) >= _MAX_MATCHES:
                    truncated = True
                    break
        if truncated:
            break
    res = {"matches": matches}
    if truncated:
        res["note"] = f"stopped at {_MAX_MATCHES} matches — refine the query or add a path filter"
    if not matches:
        res["note"] = "no matches; try a shorter/simpler query or a case variant"
    return res, scanned


def read(root: str, rel_path: str, start_line: int = 1, limit: int = _READ_DEFAULT):
    full = os.path.realpath(os.path.join(root, rel_path))
    if not full.startswith(os.path.realpath(root) + os.sep):
        return {"error": "path escapes the source root"}, 0
    if not os.path.isfile(full):
        return {"error": f"no such file: {rel_path} (use op=find_files first)"}, 0
    limit = max(1, min(int(limit or _READ_DEFAULT), _READ_MAX))
    start = max(1, int(start_line or 1))
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError as e:
        return {"error": str(e)}, 0
    window = lines[start - 1:start - 1 + limit]
    body = "\n".join(f"{start + i:5d}| {l}" for i, l in enumerate(window))
    res = {"path": rel_path, "total_lines": len(lines),
           "showing": f"{start}-{start + len(window) - 1}", "content": body}
    if start + len(window) - 1 < len(lines):
        res["note"] = f"file continues to line {len(lines)} — read again with start_line"
    return res, sum(len(l) for l in window)


def query(app: str | None, op: str, pattern: str | None = None, path: str | None = None,
          start_line: int = 1, limit: int = _READ_DEFAULT):
    """Dispatch for the agent tool. Returns (result, bytes_touched)."""
    root = source_root(app)
    if not root:
        return {"note": "no source code available for this application"}, 0
    if op == "find_files":
        return find_files(root, pattern or "**/*")
    if op == "search":
        if not pattern:
            return {"error": "search needs 'pattern' (regex or plain text)"}, 0
        return search(root, pattern, path_filter=path)
    if op == "read":
        if not path:
            return {"error": "read needs 'path' (from find_files/search results)"}, 0
        return read(root, path, start_line=start_line, limit=limit)
    return {"error": f"unknown op {op!r} (find_files | search | read)"}, 0


if __name__ == "__main__":
    import json
    import sys
    app = os.environ.get("STRATATRACE_APP", "trainticket")
    root = source_root(app)
    print("root:", root)
    if root and len(sys.argv) > 1:
        res, b = query(app, sys.argv[1], *(sys.argv[2:] or [None]))
        print(json.dumps(res, indent=1)[:2500], f"\n(bytes={b:,})")
