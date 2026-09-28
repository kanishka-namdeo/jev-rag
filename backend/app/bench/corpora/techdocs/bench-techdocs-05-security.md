# NimbusDB — Security and Compliance

Security controls in NimbusDB are enabled by default rather than opt-in. The platform
is audited annually and the current attestations are listed at the end of this
document.

## Encryption

- **At rest:** every namespace is encrypted with **AES-256 in GCM mode** by default.
  There is no configuration that disables at-rest encryption; it applies to segments,
  offsets, backups, and internal audit topics alike. Key material lives in the regional
  key-management service and never leaves the region of the data it protects.
- **In transit:** all client and inter-broker connections require **TLS 1.3**. TLS 1.2
  is accepted only for a legacy compatibility window that Enterprise customers can
  explicitly disable. Certificate rotation happens monthly with automatic pin updates.

## Key Rotation and BYOK

Default keys rotate automatically **every 90 days**. Rotation is online: new segments
are written with the new key while old segments are re-encrypted lazily during the
nightly compaction window, so there is no throughput impact. Enterprise customers can
instead bring their own keys (BYOK) hosted in their own cloud KMS; with BYOK, the
customer controls rotation policy entirely, and revoking external key access renders
NimbusDB-side ciphertext unreadable within minutes.

## Access Control

API keys carry scopes such as `messages:read`, `messages:write`, `streams:admin`, and
`keys:admin`. Console users are managed through SSO with SAML 2.0 or OIDC, and every
administrative action is written to an immutable audit topic that customers can
subscribe to in real time.

## Compliance Attestations

- SOC 2 Type II — audited annually, report available under NDA
- ISO/IEC 27001:2022 — certificate current through the calendar year
- GDPR — standard Data Processing Agreement (DPA) available in the console; EU
  customer data stays in eu-central-1 unless the customer configures replication
- HIPAA BAA — available on Enterprise contracts for US-region namespaces

## Responsible Disclosure

Security reports can be submitted to security@nimbusdb.io. The team triages within
one business day, and the program pays bounties for verifiable vulnerabilities in the
API surface, the console, and the replication protocol.
