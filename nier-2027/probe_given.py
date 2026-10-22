#!/usr/bin/env python3
"""Probe: the 'given' arm on the microservice run - skill injected, frontmatter
stripped by skillreg (so `covers:` never reaches the model), index tools only.

    python probe_given.py <rep> [defect]
"""
import os, sys, json, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
AGENT = ROOT / "Blueprint" / "agent"
sys.path.insert(0, str(AGENT))
os.chdir(AGENT)

rep = sys.argv[1] if len(sys.argv) > 1 else "1"
arm = "defect" if "defect" in sys.argv[2:] else "repair"

# .env (strip inline comments), ablation env BEFORE importing the agent
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        v = v.strip()
        v = v[1:-1] if v[:1] in "\"'" and v[-1:] == v[:1] else v.split("#", 1)[0].strip()
        os.environ.setdefault(k.strip(), v)
os.environ["CTF_INDEX_ROOT"] = str(ROOT / "nier-2027" / "ctf-index")
os.environ["PYTHONIOENCODING"] = "utf-8"
if arm == "defect":
    os.environ["ABL_FLAT_CAP"] = "6000"      # the REAL deployed v1 cap - no calibration

import skillreg
import agent_v2

sk = skillreg.load_skills(str(ROOT / "blueprints" / "skills-kernel-only"))
sk = [s for s in sk if s.name == "service-cpu-throttle"]
assert sk, "skill not found"

rd = str(ROOT / "data-sample" / "svc_cpu_cap" / "svc_cpu_cap_aggressive_steady_r1")
tp = str(ROOT / "nier-2027" / "transcripts" / f"PROBE_ss_given_{arm}_r{rep}.json")
out = agent_v2.diagnose(
    rd, skills=sk, skill_given=True, transcript_path=tp,
    problem_hint="users reported the shop was noticeably slower than usual for a while")
dx = out.get("diagnosis") or {}
print(json.dumps({"arm": arm, "rep": rep,
                  "rcs": str(dx.get("root_cause_service"))[:70],
                  "label": dx.get("fault_type"), "conf": dx.get("confidence"),
                  "what": str(dx.get("what_is_wrong"))[:220],
                  "tokens_in": (out.get("tokens") or {}).get("in")}, indent=1))
