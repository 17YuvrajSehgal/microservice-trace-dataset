"""Read-only access to a user-connected source directory, for the chat agent.

An engineer investigating an incident can point the agent at the application's code; the
agent then explores it the way a human would - list, grep, read a region - and can quote
file:line in its answer. Three rules, enforced here rather than trusted to the model:

1. JAILED. Every path resolves inside the connected root (realpath, so symlinks cannot
   escape). Anything else is refused with the reason.
2. READ-ONLY. There is no write, no execute, no shell. The three operations are directory
   listing, regex search, and line-range read.
3. DENYLISTED. Ground truth and secrets are unreadable even when the user connects a
   directory that contains them: this repo's rule is that NOTHING reachable by the agent
   may read ground_truth.json, and connecting a run directory must not become the hole.

Caps are context discipline as much as safety: grep before read, read a region not a
file, and every result fits in a model turn.
"""
from __future__ import annotations
import fnmatch, os, re

SKIP_DIRS = {".git", ".hg", "node_modules", "__pycache__", ".venv", "venv", ".tox",
             ".idea", ".vscode", "dist", "build", ".mypy_cache", ".pytest_cache"}
DENY_FILE = re.compile(r"(ground_truth|groundtruth|verification|\.env$|\.pem$|\.key$|"
                       r"id_rsa|id_ed25519|credentials|secrets?\.(json|ya?ml|txt))", re.I)
MAX_READ_LINES = 400
MAX_TREE = 400
MAX_GREP = 60
MAX_FILE_BYTES = 2_000_000       # grep/read skip anything larger
MAX_GREP_SCAN = 30_000_000       # total bytes one grep may scan

TOOL_DEFS = [
    {"name": "code_tree",
     "description": "List files and directories of the connected code repository. "
                    "Start here to learn the layout. Paths are relative to the repo root.",
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string", "description": "subdirectory to list ('' = root)"},
         "depth": {"type": "integer", "description": "levels to descend, default 2, max 4"}},
         "required": []}},
    {"name": "code_grep",
     "description": "Regex search across the connected repository. Use this BEFORE reading "
                    "files - find where something lives, then code_read the region. "
                    "Returns path, line number and the matching line.",
     "parameters": {"type": "object", "properties": {
         "pattern": {"type": "string", "description": "Python regex"},
         "glob": {"type": "string", "description": "filename filter, e.g. *.go or *.js"},
         "path": {"type": "string", "description": "limit to this subdirectory"}},
         "required": ["pattern"]}},
    {"name": "code_read",
     "description": "Read a line range of one file in the connected repository "
                    "(numbered lines, max %d per call). Read the region grep pointed at, "
                    "not whole files." % MAX_READ_LINES,
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string"},
         "start_line": {"type": "integer", "description": "1-based, default 1"},
         "end_line": {"type": "integer", "description": "default start+199"}},
         "required": ["path"]}},
]


class CodeRepo:
    def __init__(self, root: str):
        root = os.path.realpath(root)
        if not os.path.isdir(root):
            raise ValueError("not a directory: %s" % root)
        self.root = root

    # -- the jail ---------------------------------------------------------------
    def _resolve(self, rel: str) -> str:
        p = os.path.realpath(os.path.join(self.root, (rel or "").strip().lstrip("/\\")))
        if p != self.root and not p.startswith(self.root + os.sep):
            raise PermissionError("path escapes the connected repository")
        return p

    @staticmethod
    def _denied(name: str) -> bool:
        return bool(DENY_FILE.search(name))

    def _is_text(self, p: str) -> bool:
        try:
            with open(p, "rb") as fh:
                return b"\x00" not in fh.read(4096)
        except OSError:
            return False

    # -- operations -------------------------------------------------------------
    def call(self, name: str, args: dict) -> dict:
        try:
            if name == "code_tree":
                return self.tree(args.get("path") or "", int(args.get("depth") or 2))
            if name == "code_grep":
                return self.grep(args.get("pattern") or "", args.get("glob") or "",
                                 args.get("path") or "")
            if name == "code_read":
                return self.read(args.get("path") or "",
                                 int(args.get("start_line") or 1),
                                 args.get("end_line"))
            return {"error": "unknown code tool %r" % name}
        except PermissionError as e:
            return {"error": str(e)}
        except (OSError, ValueError, re.error) as e:
            return {"error": "%s: %s" % (type(e).__name__, e)}

    def tree(self, rel: str, depth: int) -> dict:
        base = self._resolve(rel)
        depth = max(1, min(int(depth), 4))
        entries, cut = [], 0
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            level = os.path.relpath(dirpath, base).count(os.sep)
            if os.path.relpath(dirpath, base) == ".":
                level = 0
            if level >= depth:
                dirnames[:] = []
                continue
            for d in dirnames:
                entries.append(os.path.relpath(os.path.join(dirpath, d), self.root)
                               .replace(os.sep, "/") + "/")
            for f in sorted(filenames):
                p = os.path.join(dirpath, f)
                if self._denied(f):
                    continue
                try:
                    entries.append("%s (%d)" % (
                        os.path.relpath(p, self.root).replace(os.sep, "/"),
                        os.path.getsize(p)))
                except OSError:
                    continue
            if len(entries) > MAX_TREE:
                cut = len(entries) - MAX_TREE
                entries = entries[:MAX_TREE]
                break
        out = {"root": os.path.basename(self.root), "entries": entries}
        if cut:
            out["truncated"] = "listing cut; descend into a subdirectory instead"
        return out

    def grep(self, pattern: str, glob: str, rel: str) -> dict:
        if not pattern:
            return {"error": "empty pattern"}
        rx = re.compile(pattern)
        base = self._resolve(rel)
        hits, scanned, nfiles = [], 0, 0
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for f in sorted(filenames):
                if self._denied(f) or (glob and not fnmatch.fnmatch(f, glob)):
                    continue
                p = os.path.join(dirpath, f)
                try:
                    sz = os.path.getsize(p)
                except OSError:
                    continue
                if sz > MAX_FILE_BYTES or not self._is_text(p):
                    continue
                scanned += sz
                nfiles += 1
                relp = os.path.relpath(p, self.root).replace(os.sep, "/")
                try:
                    for i, line in enumerate(open(p, errors="replace"), 1):
                        if rx.search(line):
                            hits.append({"path": relp, "line": i,
                                         "text": line.rstrip()[:200]})
                            if len(hits) >= MAX_GREP:
                                return {"matches": hits, "files_scanned": nfiles,
                                        "truncated": "first %d matches - narrow the "
                                                     "pattern or add a glob" % MAX_GREP}
                except OSError:
                    continue
                if scanned > MAX_GREP_SCAN:
                    return {"matches": hits, "files_scanned": nfiles,
                            "truncated": "scan budget reached - narrow with path or glob"}
        return {"matches": hits, "files_scanned": nfiles}

    def read(self, rel: str, start: int, end=None) -> dict:
        p = self._resolve(rel)
        if self._denied(os.path.basename(p)):
            return {"error": "that file is not readable through this tool"}
        if not os.path.isfile(p):
            return {"error": "no such file: %s" % rel}
        if os.path.getsize(p) > MAX_FILE_BYTES:
            return {"error": "file larger than %d bytes - grep it instead" % MAX_FILE_BYTES}
        if not self._is_text(p):
            return {"error": "binary file"}
        start = max(1, int(start))
        end = int(end) if end else start + 199
        end = min(end, start + MAX_READ_LINES - 1)
        lines, total = [], 0
        for i, line in enumerate(open(p, errors="replace"), 1):
            total = i
            if start <= i <= end:
                lines.append("%5d  %s" % (i, line.rstrip()))
        return {"path": rel.replace(os.sep, "/"), "lines_in_file": total,
                "showing": "%d-%d" % (start, min(end, total)),
                "text": "\n".join(lines)}


if __name__ == "__main__":
    import json, tempfile
    # the self-check: jail, denylist, and all three operations
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "src"))
        open(os.path.join(td, "src", "main.go"), "w").write(
            "package main\nfunc handle() {\n\tcount++ // BUG no lock\n}\n")
        open(os.path.join(td, "ground_truth.json"), "w").write('{"secret": 1}')
        r = CodeRepo(td)
        assert r.call("code_grep", {"pattern": "BUG"})["matches"][0]["line"] == 3
        assert "count++" in r.call("code_read", {"path": "src/main.go"})["text"]
        assert "ground_truth" not in json.dumps(r.call("code_tree", {}))
        assert "error" in r.call("code_read", {"path": "ground_truth.json"})
        assert "error" in r.call("code_read", {"path": "../../../etc/passwd"})
        assert "error" in r.call("code_grep", {"pattern": "secret"}) or \
            not any("ground" in m["path"] for m in
                    r.call("code_grep", {"pattern": "secret"})["matches"])
        print("coderepo self-check OK")
