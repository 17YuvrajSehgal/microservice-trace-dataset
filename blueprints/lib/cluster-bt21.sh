#!/bin/bash
# babeltrace2 2.1.2 — REQUIRED for our traces: the metadata is CTF 2 (JSON preamble), which
# bt 2.0.4 cannot parse. Its lib dir MUST precede the system one or the binary picks up the
# old .so and dies with "undefined symbol: bt_get_greatest_operative_mip_version_with_restriction".
export LD_LIBRARY_PATH=/scratch/yuvraj17/stratatrace/tools/local-bt21/lib:$LD_LIBRARY_PATH
export PATH=/scratch/yuvraj17/stratatrace/tools/local-bt21/bin:$PATH
exec babeltrace2 "$@"
