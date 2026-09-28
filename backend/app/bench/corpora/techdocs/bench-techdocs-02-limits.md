# NimbusDB — Limits and Quotas

All quotas are enforced per namespace and reset at the beginning of each calendar
month, except storage, which is a continuous high-water mark. Exceeding a soft quota
emits a warning event to the account's audit topic; exceeding a hard quota causes the
affected operation to be rejected with HTTP 429 and error code `ERR_RATE_LIMIT`.
Quota values differ substantially between tiers, so teams should pin their automation
to the numbers below for the tier they operate.

## Message Size

The maximum size of a single message, including its key, headers, and payload:

- Starter: **16 MB**
- Pro: **256 MB**
- Enterprise: **1 GB**

Messages above the tier limit are rejected at the API gateway before any storage is
allocated. Compressed payloads count toward the limit in their compressed form; the
platform performs transparent gzip and zstd compression during transit.

## Throughput

Sustained ingress throughput per namespace:

- Starter: 500 messages per second
- Pro: 5,000 messages per second
- Enterprise: 25,000 messages per second

Burst of up to twice the sustained rate is tolerated for no more than 60 seconds;
beyond that window the limiter engages and applies backpressure by throttling the
producer connection.

## Concurrent Connections

- Starter: 20 concurrent connections
- Pro: 200 concurrent connections
- Enterprise: unlimited (fair-use policy applies)

## Retention

Data retention per stream before automatic deletion:

- Starter: 7 days
- Pro: 30 days
- Enterprise: 90 days

Enterprise customers may negotiate infinite retention with tiered storage pricing for
the cold layer; archived segments older than 90 days move to object storage at a
reduced per-GB rate.

## Namespaces and Storage

- Maximum namespaces: 5 on Starter, 50 on Pro, unlimited on Enterprise.
- Maximum storage: 1 GB on Starter, 500 GB on Pro, and a custom SLA-defined ceiling
  on Enterprise negotiated per contract.
