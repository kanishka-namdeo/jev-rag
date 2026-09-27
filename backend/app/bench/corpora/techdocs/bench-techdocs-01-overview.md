# NimbusDB — Product Overview

NimbusDB is a managed message-streaming and event-store platform launched in 2024 by
Northport Cloud B.V., headquartered in Rotterdam, the Netherlands. It targets teams that
need durable, replayable event streams without operating the infrastructure themselves.
The platform is fully managed across three public regions and ships with a declarative
schema registry, exactly-once delivery semantics on the sync tier, and native consumer
group rebalancing.

## Service Tiers

NimbusDB is available in three tiers:

- **Starter** — free forever for evaluation and small side projects. Includes shared
  compute, a single region, community support via the public forum, and a maximum of
  1 GB of total storage. No uptime SLA is offered on the Starter tier.
- **Pro** — $0.28 per GB-month of storage plus $0.11 per million messages delivered.
  Dedicated compute, choice of one primary region, 99.9% monthly uptime SLA, and
  email support with an 8-business-hour response target. Most production workloads
  at small and mid-sized companies run on Pro.
- **Enterprise** — custom contract pricing. Multi-region replication, data-residency
  guarantees, a 99.99% uptime SLA with financial penalties, bring-your-own-key
  encryption (BYOK), and a named technical account manager. Enterprise contracts are
  annual or multi-year.

## Typical Use Cases

Customers commonly use NimbusDB for order-event capture in e-commerce, clickstream
ingestion for analytics, change-data-capture pipelines feeding a lakehouse, and as the
durable backing store for event-sourced domains. Financial services teams use the
exactly-once sync tier for ledger writes, while gaming studios prefer the async tier
for telemetry fan-out where latency matters more than immediacy.

## Getting Started

New workloads should begin on the Starter tier, enable schema registry validation from
day one, and graduate to Pro when steady-state storage exceeds 1 GB or when an uptime
SLA becomes contractually necessary. The tier can be switched at any time from the
console without downtime; prorated billing applies from the moment of the switch.
