# Vendored package: models

Copied verbatim on 2026-07-27 from the sibling `adaptive_tracer` project at
commit `405e49e2fc494e949c0fad65086e66f98df582f8` ("added 100 user results",
2026-03-31). The `microservice/` analysis scripts import this package
(`from models import LSTM, Transformer`) after inserting the repo root on
`sys.path`; before vendoring they only ran inside the parent
`adaptive_tracer` checkout.

This copy is now the authoritative version for this repository — apply fixes
here, not in `adaptive_tracer`. Requires: torch.
