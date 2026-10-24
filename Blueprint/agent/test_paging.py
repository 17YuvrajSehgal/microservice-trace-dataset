#!/usr/bin/env python3
"""Checks for page_result() - the safe replacement for the v1 flat-cut defect studied in
nier-2027/. Every row/line must arrive exactly once, in order, never split, never lost, and
the agent must always be told plainly whether more remains.

    python test_paging.py
"""
import json
import sys

import utils


def _list_result(n_spawned, n_resident):
    return {
        "present_for_only_part_of_the_recording": [
            {"procname": "stress-ng-cpu", "pid_ns": 4026533600 + i} for i in range(n_spawned)],
        "present_throughout": [
            {"procname": "java", "pid_ns": 4026532700 + i} for i in range(n_resident)],
        "how_to_read": "repeats on every page",
    }


def _walk(obj, cap, max_pages=100):
    """Page through to completion. Returns (pages, all_valid)."""
    state = {}
    pages = []
    for page in range(1, max_pages + 1):
        text, complete = utils.page_result(obj, page, cap, state)
        json.loads(text)          # raises if a page is ever invalid JSON
        pages.append(json.loads(text))
        if complete:
            return pages, True
    return pages, False


def test_list_fields_fully_recovered():
    obj = _list_result(40, 128)       # the exact shape that lost 0/128 under the v1 defect
    pages, done = _walk(obj, 2000)
    assert done, "never reached completion"
    early = [x["pid_ns"] for p in pages
             for x in p.get("present_for_only_part_of_the_recording", [])]
    late = [x["pid_ns"] for p in pages for x in p.get("present_throughout", [])]
    assert sorted(early) == [4026533600 + i for i in range(40)]
    assert sorted(late) == [4026532700 + i for i in range(128)]
    assert len(early) == len(set(early)) and len(late) == len(set(late)), "duplicate rows"


def test_text_field_never_splits_a_line():
    lines = [f"line {i} procname=java pid_ns=402653{i:04d}" for i in range(400)]
    obj = {"cmd": ["idx_dump.py"], "exit": 0, "stdout": "\n".join(lines)}
    pages, done = _walk(obj, 3000)
    assert done
    recovered = [l for p in pages for l in p.get("stdout", "").split("\n") if l]
    assert sorted(recovered) == sorted(lines), "a line was lost, split, or duplicated"


def test_out_of_order_page_is_refused_not_guessed():
    obj = _list_result(10, 10)
    state = {}
    utils.page_result(obj, 1, 500, state)
    text, complete = utils.page_result(obj, 5, 500, state)   # skip ahead
    d = json.loads(text)
    assert not complete
    assert "page: 2" in d["_note"], "must name the correct next page, not silently comply"


def test_small_result_is_untouched():
    obj = {"a": 1, "b": "short"}
    text, complete = utils.page_result(obj, 1, 2000, {})
    assert json.loads(text) == obj
    assert complete


def test_unpageable_oversized_result_says_so_rather_than_slicing():
    obj = {"blob": "x" * 5000}      # no rows, no lines - nothing safe to cut on
    text, complete = utils.page_result(obj, 1, 2000, {})
    d = json.loads(text)
    assert complete
    assert "narrow" in d["_note"].lower()
    assert "blob" not in d, "must not fall back to a silent byte slice"


def test_real_production_trace_fatal_case_is_recoverable():
    """The paper's own worst case: at the real deployed cap, the v1 defect delivered 0 of
    128 late-list records. This must now recover all of them."""
    import importlib
    import os

    index_root = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "nier-2027", "ctf-index")
    run_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "data-sample", "svc_cpu_cap",
        "svc_cpu_cap_aggressive_steady_r1")
    if not os.path.isdir(index_root) or not os.path.isdir(run_dir):
        print("  SKIP (local index/trace not present in this checkout)")
        return
    os.environ["CTF_INDEX_ROOT"] = index_root
    import ctf_tool
    importlib.reload(ctf_tool)
    res = ctf_tool.ctf_proclife(run_dir)
    pages, done = _walk(res, 6000)       # the REAL shipped cap, not a calibrated one
    assert done
    late = [x for p in pages for x in p.get("present_throughout", [])]
    assert len(late) == len(res["present_throughout"]) == 128
    java = [x for x in late if "java" in x.get("procname", "").lower()]
    assert len(java) == 5, "the throttled culprit's own records must all be recoverable"


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok    {t.__name__}")
        except Exception as e:                                        # noqa: BLE001
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.path.insert(0, ".")
    raise SystemExit(main())
