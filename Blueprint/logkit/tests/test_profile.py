import pytest

from logkit.profile import ProfileError, SourceProfile, _iso_utc, load_profile

BASE = {"id": "x", "files": ["logs/*.log"], "line": r"^(?P<ts>\S+) (?P<msg>.*)$",
        "ts_format": "iso_utc", "entity": {"from": "filename"}, "kind": "container"}


def test_docker_profile_reads_entities_and_skips_the_span_relay(runs):
    prof = load_profile("docker_compose")
    skipped = {}
    recs = list(prof.records(runs["fault"], skipped))
    assert {r.entity for r in recs} == {"catalogue", "front-end", "orders"}
    assert skipped == {"orders": 200}
    assert all(r.kind == "container" for r in recs)
    assert all("LoggingSpanExporter" not in r.msg for r in recs)


def test_profile_never_reaches_ground_truth(runs):
    prof = load_profile("docker_compose")
    texts = " ".join(r.msg for r in prof.records(runs["fault"]))
    assert "SECRET" not in texts
    assert all("ground_truth" not in p.name for p in prof.paths(runs["fault"]))


@pytest.mark.parametrize("pattern", ["ground_truth.json", "*", "../other/*.log", "/etc/*.log",
                                     "verification*", "logs/../ground_truth.json"])
def test_unsafe_file_patterns_are_refused(runs, pattern):
    with pytest.raises(ProfileError):
        prof = SourceProfile.from_dict({**BASE, "files": [pattern]})
        prof.paths(runs["fault"])        # "*" passes the load check and is caught here


def test_bad_profiles_are_refused():
    with pytest.raises(ProfileError):
        SourceProfile.from_dict({**BASE, "line": r"^(?P<msg>.*)$"})          # no ts group
    with pytest.raises(ProfileError):
        SourceProfile.from_dict({**BASE, "kind": "pod"})
    with pytest.raises(ProfileError):
        SourceProfile.from_dict({k: v for k, v in BASE.items() if k != "ts_format"})
    with pytest.raises(ProfileError):
        load_profile("no_such_profile")


def test_unknown_clock():
    assert SourceProfile.from_dict({**BASE, "clock": {"status": "unknown"}}).clock_offset_s is None
    assert SourceProfile.from_dict(BASE).clock_offset_s == 0.0


def test_iso_utc_keeps_nanoseconds():
    assert _iso_utc("2026-09-05T15:18:40.123456789Z") == pytest.approx(1788621520.123456789)
    assert _iso_utc("2026-09-05T15:18:40Z") == 1788621520
    with pytest.raises(ValueError):
        _iso_utc("15:18:40")
