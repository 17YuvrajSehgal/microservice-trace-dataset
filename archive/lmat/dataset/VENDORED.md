# Vendored package: dataset

Copied verbatim on 2026-07-27 from the sibling `adaptive_tracer` project at
commit `405e49e2fc494e949c0fad65086e66f98df582f8` ("added 100 user results",
2026-03-31). The `microservice/` analysis scripts use
`from dataset.Dictionary import Dictionary` (and `root_cause_vectors.py`
loads `dataset/Dictionary.py` by file path); before vendoring they only ran
inside the parent `adaptive_tracer` checkout.

`IterableDataset.py` is included because `dataset/__init__.py` imports it
(any `dataset.*` import executes the package `__init__`), and it supports
replication of the earlier Apache-corpus experiments.

This copy is now the authoritative version for this repository — apply fixes
here, not in `adaptive_tracer`. Requires: torch (IterableDataset), stdlib
only for Dictionary.
