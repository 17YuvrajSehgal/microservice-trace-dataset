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


@pytest.mark.parametrize("name,entity", [
    ("docker-compose_front-end_1.log", "front-end"),
    ("docker-compose_carts-db_1.log.gz", "carts-db"),
    ("trainticket_ts-order-service_1.log", "ts-order-service"),
    ("mysql.log", "mysql"),
])
def test_entity_names_of_both_applications(name, entity):
    from pathlib import Path
    assert load_profile("docker_compose").entity_of(Path(name), None) == entity


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


def test_a_service_named_verification_is_readable(tmp_path):
    """Train Ticket's ts-verification-code-service is a service, not the label file."""
    from conftest import write_run
    run = write_run(tmp_path, "tt_r1", False)
    (run / "logs" / "trainticket_ts-verification-code-service_1.log").write_text(
        "2026-09-05T15:18:41.000000000Z started\n")
    prof = load_profile("docker_compose")
    assert "ts-verification-code-service" in {r.entity for r in prof.records(run)}
    assert not any(p.name.startswith("verification") for p in prof.paths(run))


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
