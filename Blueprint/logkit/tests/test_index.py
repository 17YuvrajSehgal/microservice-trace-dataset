import pytest

from logkit.index import duration_ms
from logkit.tools import logidx as L
from logkit_synth import FAULT_LAT_AT, SPAN, T0


def test_duration_ms():
    assert duration_ms("1.27ms") == pytest.approx(1.27)
    assert duration_ms("980.311µs") == pytest.approx(0.980311)
    assert duration_ms("694ns") == pytest.approx(694e-6)
    assert duration_ms("1m2.5s") == pytest.approx(62500)
    assert duration_ms("null") is None


def test_quantile_is_within_one_bin():
    hist = {}
    for ms in [1.0] * 60 + [50.0] * 40:
        b = L.bin_of(ms)
        hist[b] = hist.get(b, 0) + 1
    assert L.quantile(hist, 0.5) == pytest.approx(1.0, rel=0.13)
    assert L.quantile(hist, 0.9) == pytest.approx(50.0, rel=0.13)
    assert L.quantile({}, 0.5) is None


def test_index_round_trip(indexes):
    idx = L.load(str(indexes["fault"]))
    assert idx.t0 == T0 and idx.clock_aligned
    assert set(idx.entities) == {"catalogue", "front-end", "orders", "orders-db"}
    cat, orders = idx.entities["catalogue"], idx.entities["orders"]
    assert cat.lines == 5 * SPAN and len(cat.templates) == 1          # repeats share a template
    assert orders.lines == SPAN and orders.skipped == SPAN
    assert idx.entities["orders-db"].lines == 0
    before = cat.latency_hist("List", T0, T0 + FAULT_LAT_AT)
    after = cat.latency_hist("List", T0 + FAULT_LAT_AT, T0 + SPAN)
    assert L.quantile(before, 0.5) == pytest.approx(1.27, rel=0.13)
    assert L.quantile(after, 0.5) == pytest.approx(50.2, rel=0.13)
    assert cat.lines_in(T0, T0 + 10) == 50


def test_resolve_time():
    assert L.resolve_time("15:18:50", T0) == T0 + 10
    assert L.resolve_time("2026-09-05 15:18:50", T0) == T0 + 10
    assert L.resolve_time("00:00:10", T0 + 8.6 * 3600) == T0 - 55120 + 86400 + 10   # after midnight
    with pytest.raises(ValueError):
        L.resolve_time("soon", T0)


def test_reader_refuses_another_schema(tmp_path):
    p = tmp_path / "x.logidx.json"
    p.write_text('{"schema": 99, "entities": {}}')
    with pytest.raises(ValueError, match="schema"):
        L.load(str(p))
