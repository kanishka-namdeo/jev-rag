# Scripts DOX

## Purpose

- Own the setup / build / run scripts that make the project reproducible on a fresh machine.

## Ownership

- `setup_local_models.sh` — downloads Jev-Style GGUF (+ runtime files) and builds `jev-score`
  from llama.cpp (idempotent phases; safe to re-run)
- `setup_backend.sh` — creates `backend/.venv` via uv and installs requirements
- `backend_service.sh` — runs uvicorn (used by mini-services and the self-healing launcher)
- `dev.sh` — starts backend + frontend together for local development
- `init-fullstack-reference.sh` — reference copy of the sandbox init script (documentation only)
- `backend/scripts/smoke_jev.py` — engine smoke test (noul warm-up, rerank, sufficiency+routing)
- `backend/scripts/experiment_rerank*.py` — validated decision-pattern experiments (do not delete;
  they document why the rerank pattern looks the way it does)
- `test-assets/` — sample documents for manual testing (unindexed)

## Local Contracts

- Scripts must be idempotent and safe to re-run (size checks, resume flags)
- Downloads must use `--speed-limit`/`--speed-time` so stalls fail fast; always resume (`-C -`)
- No secrets in scripts; credentials only via env files

## Verification

- Re-run each setup script after editing it; it must reach "STATUS: SUCCESS" without side effects
  on an already-provisioned machine

## Child DOX Index

| Child | Scope |
| --- | --- |
| (none) | Flat script directory |
