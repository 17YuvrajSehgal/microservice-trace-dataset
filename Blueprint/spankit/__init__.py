"""spankit: the request traces (OTLP spans) of a run, read once into a service call graph.

Used to narrow where to look (LOGS-PLAN.md section 6.5): a service whose logs change is usually
the CALLER of the faulty one, so the shortlist is the flagged services plus the services they
call. Layout, as in logkit:

    spankit.otlp        streams an OTLP JSON-lines file into Span records (bad lines counted)
    spankit.graph       Span records -> the call graph of one run, and its blind spots
    spankit.build       CLI: python -m spankit.build <run_dir> ... --out-dir DIR
    spankit/tools/      standard library only: read a graph, list callers and callees

Nothing here opens anything in a run directory except `otlp/spans.jsonl`.
"""
from spankit.tools.callgraph import SCHEMA_VERSION

__all__ = ["SCHEMA_VERSION"]
