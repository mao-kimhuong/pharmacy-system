# Infrastructure

- `postgres/init/` – first-start script: one database + one user per service.
- Production additions planned in docs/spec.md (Security & reliability):
  hot standby with streaming replication, pgBackRest (WAL archiving + nightly
  full backup, off-site), Patroni once there are several branches,
  RabbitMQ quorum queues, object storage replication (store chosen before S4), Prometheus + Grafana + Loki + Sentry.
