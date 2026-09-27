# NimbusDB — Architecture

NimbusDB separates durability from delivery latency by offering two replication tiers
that clients choose per stream. Both tiers share the same storage engine, control
plane, and observability stack, which is why a namespace can mix sync-tier and
async-tier streams without any operational split.

## Replication Tiers

- **Sync tier (strong consistency).** Writes are acknowledged only after a quorum of
  three regions confirms the write, giving linearizable reads and exactly-once
  semantics. Median write latency is 38 ms within Europe and 91 ms intercontinental.
  Ledger writes and order capture should always use the sync tier.
- **Async tier (eventual consistency).** Writes acknowledge after the primary region
  commits; followers replicate in the background with cross-region replication lag
  typically under 2 seconds. Telemetry, clickstream, and fan-out workloads run on the
  async tier, trading immediacy for roughly six times higher throughput per node.

## Storage Engine

Segments are stored on an LSM-tree based engine with nightly compaction windows
scheduled per region between 01:00 and 04:00 local time. Compaction rewrites adjacent
small segments into 1 GB targets and applies schema-registry-aware transcoding when
a topic evolves. Cold segments are checksummed on read; any mismatch triggers
transparent re-replication from the remaining replicas.

## Regions and Data Residency

NimbusDB operates in three public regions: **eu-central-1 (Frankfurt)**,
**us-east-1 (Northern Virginia)**, and **ap-southeast-2 (Sydney)**. Enterprise
contracts can pin namespaces to a single region for data-residency purposes, in which
case neither replicas nor backups leave that region. Pro-tier namespaces may select a
primary region at creation time; the choice is immutable afterwards. Cross-region
async replication between all three regions is available on Enterprise only.

## Consumer Groups and Rebalancing

Consumers organize into groups with persistent offset storage on the control plane.
Rebalancing uses a cooperative incremental protocol that pauses only partitions being
migrated, typically completing in under 400 ms for groups of up to 200 members. Sticky
partition assignment preserves cache locality across rebalances where possible.

## Failure Modes and Recovery

Broker loss triggers automatic leader election within a 3-second detection window.
Region loss on the sync tier blocks writes until the quorum is restored, by design;
async-tier streams continue accepting writes against the surviving regions. Backups
are taken every 6 hours and retained for 14 days on all tiers.
