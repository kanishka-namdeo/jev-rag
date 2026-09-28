# NimbusDB — REST API Reference

The NimbusDB API is a RESTful HTTP JSON API. The base URL for all production calls is
`https://api.nimbusdb.io/v1`. Every request must present a bearer API key in the
`Authorization` header. API keys are scoped to a namespace and can be created, rotated,
and revoked from the console or programmatically through the keys endpoint.

## Core Endpoints

- `GET /v1/namespaces` — lists all namespaces visible to the API key, with per-namespace
  quota usage. Results are paginated with a cursor parameter; the default page size is
  50 and the maximum is 200.
- `POST /v1/namespaces` — creates a new namespace. The request body must contain a
  unique `namespace_id` (3–48 characters, lowercase alphanumeric and hyphens) and an
  optional retention override.
- `GET /v1/messages` — reads messages from a stream, supporting both live tailing and
  time-anchored replay using the `from_timestamp` query parameter.
- `POST /v1/messages` — publishes one or a batch of up to 500 messages. Batches are
  atomic: either all messages are durable or none are.
- `DELETE /v1/streams/{stream}` — deletes a stream and all of its segments. This
  operation is irreversible and requires the `streams:admin` scope.

## Authentication and Idempotency

Requests use `Authorization: Bearer <api-key>`. Publish calls may include an
`Idempotency-Key` header; the server remembers keys for 24 hours and returns the
original response for duplicates, which makes producer retries safe.

## Rate Limits

Each API key is limited to **120 requests per minute** across all endpoints. When the
limit is exceeded the API responds with HTTP status **429** and error code
**`ERR_RATE_LIMIT`**, together with a `Retry-After` header expressed in seconds.
Clients should implement exponential backoff with jitter, capped at 30 seconds.

## Error Codes

| Code | HTTP | Meaning |
|---|---|---|
| ERR_NOT_FOUND | 404 | Resource does not exist or is not visible to this key |
| ERR_VALIDATION | 422 | Request body failed schema validation |
| ERR_RATE_LIMIT | 429 | Rate limit or quota exceeded |
| ERR_CONFLICT | 409 | Concurrent modification of the same resource |

## Webhooks

Consumer webhooks can be registered per stream. Payloads are signed with HMAC-SHA256;
the signature arrives in the `X-Nimbus-Signature` header and should be verified against
the endpoint's secret before processing. Failed deliveries retry three times with
exponential spacing and then park on a dead-letter queue for manual inspection.
