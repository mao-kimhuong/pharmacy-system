# 0001 – Microservices with one database per service

- Status: accepted
- Date: 2026-10-25

## Decision

14 FastAPI services behind Traefik. Each owns one PostgreSQL database and is
the only one allowed to read or write it. Cross-service data comes from an API
call or from a local copy built from events (RabbitMQ, transactional outbox).

## Consequences

- Services can be built, tested and deployed one by one (one sprint per group).
- No joins across services; reports use read models in the reports service.
- The sale flow is a saga with compensations (release stock, correct register).
