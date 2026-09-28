# Security Policy

## Reporting a vulnerability

If you find something security-relevant — leaked credentials, prompt-injection
or data-exfiltration vectors in the ingestion path, unsafe defaults — please
**do not open a public issue**.

Instead, use GitHub's private vulnerability reporting:
**Security → Report a vulnerability** on this repo, or contact the maintainer
directly via their GitHub profile. Please include reproduction steps and, where
applicable, the pipeline (traditional / hybrid) and the trace panel output.

Expect a response within a few days. Anything involving exposed keys is treated
as urgent.

## Handling of leaked credentials

This project's history was already rewritten once to purge a leaked API key
(git-filter-repo, 2026-09-29). If you notice a live credential in any commit,
**report it privately first** — do not open a PR that quotes it. Rotate the
credential immediately, then report so the history can be scrubbed.

## Scope notes

- The app is designed to run **locally** (localhost backend + frontend); it is
  not hardened for public internet exposure. Don't deploy it facing the open
  internet without your own auth/TLS in front.
- Cloud calls go only to the OpenAI-compatible endpoint you configure in
  `backend/.env`. Uploaded documents and the vector store stay on your disk.
