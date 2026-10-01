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

- The backend binds to **`127.0.0.1` by default** (`JEVRAG_HOST`, see `backend/.env.example`).
  On that default only processes on your own machine can reach the API.
- The app has **no authentication**. Setting `JEVRAG_HOST=0.0.0.0` is therefore a
  deliberate trust decision: it grants every host on the network full read/write API
  access — including uploading and **deleting documents and conversations** — with no
  credentials asked. There is no auth/TLS layer to add in front of a bound-all
  instance either; don't expose the port beyond loopback unless you accept that.
- CORS allows **only the configured frontend origin(s)** (`JEVRAG_FRONTEND_ORIGIN`,
  default `http://localhost:3000` and `http://127.0.0.1:3000`; never a wildcard).
  This is defense-in-depth against a *foreign web page in your browser* driving the
  local port with cross-origin fetches. It is **not** what carries the app's own
  traffic: the frontend reaches the backend through a server-side Next.js rewrite
  (`/backend-api/*`), where CORS does not apply at all.
- Known residual limitation that neither control closes: **DNS rebinding**. A
  malicious page whose domain resolves to `127.0.0.1` makes its requests to the local
  port same-origin, and the backend does not validate the `Host` header. Treat the
  browser-driven surface as narrowed, not closed.
- Cloud calls go only to the OpenAI-compatible endpoint you configure in
  `backend/.env`. Uploaded documents and the vector store stay on your disk.
- Private vulnerability reporting must be **enabled in repo Settings** — it is a
  setting, not a file. The form above ("Security → Report a vulnerability") exists
  only while Settings → Security and insights keeps "Report a vulnerability"
  enabled; if it's missing, use the maintainer-contact route instead.
