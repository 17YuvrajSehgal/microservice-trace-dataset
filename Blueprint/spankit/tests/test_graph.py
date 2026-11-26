import shutil
import subprocess
import sys

from spankit.graph import build_graph, write_graph
from spankit.otlp import ReadStats, read_spans, spans_path
from spankit.tools import callgraph as C


def edges(g):
    return {(e["caller"], e["callee"]): e["calls"] for e in g["edges"]}


def test_reader_skips_a_cut_line_and_counts_it(run):
    stats = ReadStats()
    spans = list(read_spans(spans_path(run), stats))
    assert stats.bad_lines == 1 and stats.spans == len(spans) == 22      # 5 + 8 + 4 + 2 + 1 + 1 + 1


def test_edges_by_link_attribute_and_address(run):
    g = build_graph(run)
    assert edges(g) == {("front-end", "catalogue"): 4, ("front-end", "orders"): 1,
                        ("orders", "payment"): 2,          # IP only, found by the span link
                        ("orders", "ip:10.9.9.9"): 1,      # nothing names this address
                        ("carts", "toxiproxy"): 1, ("shipping", "rabbitmq"): 1,
                        ("queue-master", "rabbitmq"): 1}
    via = {(e["caller"], e["callee"]): e["via"] for e in g["edges"]}
    assert via[("front-end", "catalogue")] == {"span_link": 4}
    assert via[("front-end", "orders")] == {"attribute": 1}
    assert via[("orders", "payment")] == {"span_link": 2}
    assert g["unresolved_ips"] == ["10.9.9.9"]


def test_a_proxy_keeps_the_database_it_fronts(run, tmp_path):
    g = build_graph(run)
    assert [e["db"] for e in g["edges"] if e["callee"] == "toxiproxy"] == [["mysql"]]
    p = tmp_path / "g.callgraph.json"
    write_graph(g, p)
    assert C.load(str(p)).databases("carts") == {"mysql"}


def test_gaps_are_reported_not_hidden(run):
    g = build_graph(run)
    assert g["no_outgoing"] == ["catalogue", "payment"]
    assert g["silent_callees"] == ["rabbitmq", "toxiproxy"]


def test_no_spans_is_not_no_calls(tmp_path, capsys):
    (tmp_path / "bare_r1").mkdir()
    g = build_graph(tmp_path / "bare_r1")
    assert g["source"] is None and g["edges"] == []
    p = tmp_path / "bare.callgraph.json"
    write_graph(g, p)
    C.main([str(p)])
    assert capsys.readouterr().out.startswith("NO SPANS")


def test_reader_and_cli(run, tmp_path, capsys):
    p = tmp_path / "g.callgraph.json"
    write_graph(build_graph(run), p)
    gr = C.load(str(p))
    assert gr.callees("front-end") == {"catalogue": 4, "orders": 1}
    assert gr.callers("payment") == {"orders": 2}
    assert not gr.known_callees("catalogue") and not gr.known_callees("toxiproxy")
    C.main([str(p), "--around", "catalogue"])
    out = capsys.readouterr().out
    assert "CALLEES of catalogue: unknown (no outgoing spans)" in out
    assert "CALLERS of catalogue: front-end (4)" in out


def test_tool_runs_as_a_copied_script_with_the_standard_library_only(run, tmp_path):
    p = tmp_path / "g.callgraph.json"
    write_graph(build_graph(run), p)
    shutil.copy(C.__file__, tmp_path / "callgraph.py")
    r = subprocess.run([sys.executable, "-E", "-s", str(tmp_path / "callgraph.py"), str(p)],
                       capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "toxiproxy (1; db mysql)" in r.stdout and "unknown (writes no spans)" in r.stdout


def test_builder_never_reads_the_label(run, monkeypatch):
    opened = []
    real = open

    def spy(path, *a, **k):
        opened.append(str(path))
        return real(path, *a, **k)

    monkeypatch.setattr("builtins.open", spy)
    build_graph(run)
    assert opened and all("ground_truth" not in p for p in opened)


def test_reader_refuses_an_old_schema(tmp_path):
    import json

    import pytest
    p = tmp_path / "old.callgraph.json"
    p.write_text(json.dumps({"schema": 1, "edges": []}))
    with pytest.raises(ValueError, match="schema"):
        C.load(str(p))
