| Cause                        | Families                                                         |
|------------------------------|------------------------------------------------------------------|
| Too much work                | `code_n_plus_one`, `code_serial_awaits`, `code_event_loop_block` |
| Waiting for CPU              | `svc_cpu_cap`, `anomaly_cpu`, `noisy_neighbor`, `fork_storm`     |
| Waiting for disk             | `anomaly_disk`                                                   |
| Waiting for network          | `anomaly_net`, `svc_net`, `nagle_delayed_ack`, `dns_delay`       |
| Waiting for a lock           | `lock_contention`, `priority_inversion`, `code_lock_across_io`   |
| Waiting for a remote service | `slow_db`, `conn_pool_exhaustion`                                |
