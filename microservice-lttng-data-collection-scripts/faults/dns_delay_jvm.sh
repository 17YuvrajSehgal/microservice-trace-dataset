#!/bin/bash
# Fault recipe: unreliable name resolution for a JAVA service (the JVM's resolver).
#
# The same fault as dns_delay.sh (a share of the service's DNS queries is dropped inside its
# own network namespace), aimed at a Spring Boot service. dns_delay targets the Node front-end,
# whose resolver is musl's; the JVM resolves through its own cache (30 s for good answers by
# default) and glibc, so the lookups are fewer and look different.
#
# Pre-registered expectations (v3, CANDIDATE-PROBLEMS D11): the KERNEL shows repeated DNS
# queries from the JVM with seconds between the tries, and a stall before a new connection;
# lookups are rare because of the JVM cache and connection pools, so METRICS may show nothing;
# what users see is measured in the calibration, not assumed.
#
# Usage: ./dns_delay_jvm.sh inject [subtle|aggressive] | prove | cleanup | status
export TARGET_SVC="${TARGET_SVC:-orders}"
export DNS_FAULT_NAME="dns_delay_jvm"
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/dns_delay.sh" "$@"
