# The image every workload container runs.
#
# Was `python:3.12-slim` straight from Docker Hub. That was fine until conn_pool_exhaustion
# needed to actually LOG IN to MySQL rather than just open a socket, which needs a driver.
#
# Baking it means the campaign does not pip-install anything per run - 300+ runs each reaching
# out to the network for the same package is a slow, fragile step that can only fail.
#
# cryptography is not optional: MySQL 8 (Train Ticket's shared database) defaults to
# caching_sha2_password, and PyMySQL cannot complete that handshake without it. Sock Shop's
# MySQL 5.7 does not need it, so leaving it out would have worked on one application and failed
# on the other - the exact asymmetry v2 exists to remove.
#
#   docker build -t stratatrace-workload:v1 faults/workloads
FROM python:3.12-slim
RUN pip install --no-cache-dir pymysql==1.1.1 cryptography==43.0.1
