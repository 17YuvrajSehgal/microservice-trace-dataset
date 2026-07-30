#!/usr/bin/env python3
"""MCP server — the agent-facing interface to collection-aware RCA.

Exposes the two-phase, collection-aware loop as MCP tools so an agent (Claude Code,
etc.) drives it from a plain-language problem:
    discover_skills("my database is slow")   -> ranked skills
    phase1_requirements(skill, problem)       -> the scoped collection spec (the differentiator)
    run_skill(skill, problem)                 -> kernel-deep verdict + dashboard path
    query_result / list_runs                  -> inspect prior runs

Runs over stdio. Requires `mcp` (pip install "mcp[cli]"); if absent, use demo_cli.py —
the CLI has the identical logic and is the demo fallback. No stdout prints here (stdio
is the JSON-RPC channel); all human output flows through tool return values.
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "engine"))
import demo_cli

try:
    from mcp.server.fastmcp import FastMCP
except Exception as ex:  # pragma: no cover
    sys.stderr.write(f"[mcp_server] `mcp` package not available ({ex}). Use demo_cli.py instead.\n")
    raise SystemExit(1)

mcp = FastMCP("collection-aware-rca")

@mcp.tool()
def discover_skills(problem: str) -> list:
    """Match a plain-language problem statement to diagnostic skills, ranked by relevance.
    Returns each skill's name, its decisive modality, and the fault it targets."""
    return demo_cli.discover(problem)

@mcp.tool()
def phase1_requirements(skill: str, problem: str = "") -> dict:
    """Phase 1 — emit the machine-readable *collection spec* for a skill: exactly which
    kernel events/syscalls, on which services, over what window, plus the correlating
    OTel/log/metric scope and the lttng capture command. This is the collection-aware
    differentiator — surface it to the user before collecting anything."""
    return demo_cli.phase1(skill)

@mcp.tool()
def run_skill(skill: str, problem: str = "", max_seconds: int = 0) -> dict:
    """Phase 2 — run the skill (replay over a collected run): scoped kernel wait-attribution
    + trace/log/metric correlation, then a deterministic root-cause verdict. Returns the
    verdict, what was ruled out, the decisive modality, the data-touched payoff, whether it
    matched hidden ground truth, and a path to the self-contained HTML dashboard."""
    res = demo_cli.execute(skill, problem=problem or None,
                           max_seconds=(max_seconds or None))
    v = res["verdict"]
    return {"problem": res["problem_statement"], "skill": res["skill"], "mode": res["mode"],
            "root_cause": v["root_cause"], "decisive_modality": v["decisive_modality"],
            "confidence": v["confidence"], "ruled_out": v.get("ruled_out", []),
            "evidence": v.get("evidence", []),
            "data_touched_mb": v.get("data_touched_mb"), "reduction_x": v.get("reduction_x"),
            "correct_vs_ground_truth": res.get("correct"),
            "dashboard": res.get("dashboard_html")}

@mcp.tool()
def query_result(skill: str) -> dict:
    """Return the stored result.json for a previously-run skill (verdict + full evidence)."""
    p = os.path.join(demo_cli.RESULTS, f"{skill}.json")
    if not os.path.exists(p): return {"error": f"no result for {skill}; run_skill first"}
    d = json.load(open(p)); d.pop("ground_truth", None)
    return d

@mcp.tool()
def list_runs() -> dict:
    """List the registered replay runs (one per fault family) available to run_skill."""
    return {fs: {k: v for k, v in reg.items() if k in ("skill","problem")}
            for fs, reg in demo_cli.load_runs().items() if not fs.startswith("_")}

@mcp.resource("skill://{name}")
def skill_doc(name: str) -> str:
    """The raw skill.json contract for a skill."""
    return json.dumps(demo_cli.load_skill(name), indent=2)

@mcp.prompt()
def diagnose(problem: str) -> str:
    """Guide the agent through the collection-aware loop for a reported problem."""
    return (f"A user reports: “{problem}”.\n"
            "1) Call discover_skills to pick the right diagnostic skill.\n"
            "2) Call phase1_requirements and SHOW the user the scoped collection plan "
            "(the point: we decide *what to collect* from the problem — surface it).\n"
            "3) Call run_skill and present the verdict: root cause, what was ruled out, the "
            "decisive modality, the data-touched payoff, and the dashboard link.")

if __name__ == "__main__":
    mcp.run()
