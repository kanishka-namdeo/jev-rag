"""Server defaults are a user-facing contract: the README claims local-first, so the
shipped default must bind loopback and must not accept any origin. Hermetic — no models,
no network. Run: cd backend && .venv/bin/python -m pytest tests -v"""
from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="jevrag-sd-")
os.environ.setdefault("JEVRAG_LAZY_MODELS", "1")
os.environ.setdefault("JEVRAG_DATA_DIR", _TMP)
os.environ.setdefault("JEVRAG_DASHSCOPE_API_KEY", "test-key")


def _fresh_settings(monkeypatch, **overrides):
    """Settings for one env override, restored afterwards.

    Every override goes through monkeypatch (never a bare os.environ write) and the
    lru_cache is cleared on both sides, so no test can leak a mutated JEVRAG_* env or a
    mutated cache into the files pytest runs after this one (test_basic.py's create_app()
    would otherwise see it). _env_file=None keeps backend/.env — a real file on a dev box,
    gitignored — from silently overriding what a default test actually asserts.
    """
    from app.config import Settings, get_settings

    get_settings.cache_clear()
    for k, v in overrides.items():
        monkeypatch.setenv(f"JEVRAG_{k.upper()}", v)
    try:
        return Settings(_env_file=None)
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_default_host_is_loopback(monkeypatch):
    from app.config import Settings

    monkeypatch.delenv("JEVRAG_HOST", raising=False)
    assert Settings(_env_file=None).host == "127.0.0.1"


def test_cors_never_allows_wildcard_by_default(monkeypatch):
    from fastapi.middleware.cors import CORSMiddleware

    from app.config import Settings
    from app.main import create_app

    monkeypatch.delenv("JEVRAG_FRONTEND_ORIGIN", raising=False)
    mw = [m for m in create_app().user_middleware if m.cls is CORSMiddleware]
    assert mw, "CORSMiddleware missing"
    assert "*" not in mw[0].kwargs["allow_origins"], mw[0].kwargs["allow_origins"]
    # The middleware check above reflects the *effective* config — a developer's own
    # backend/.env (gitignored, real on a dev box) can set JEVRAG_FRONTEND_ORIGIN and decide
    # its outcome. _env_file=None bypasses only the dotenv file (pydantic-settings still
    # reads the process env), so delenv the origin first, then construct Settings
    # (_env_file=None) to prove the SHIPPED default excludes the wildcard regardless of
    # ambient files or env.
    assert "*" not in Settings(_env_file=None).cors_origins


def test_cors_origins_follow_env(monkeypatch):
    s = _fresh_settings(monkeypatch,
                        frontend_origin="http://example.test:3000,http://localhost:3000")
    assert s.cors_origins == ["http://example.test:3000", "http://localhost:3000"]


def test_env_example_defaults_match_code():
    """backend/AGENTS.md: template and code defaults must agree — they had drifted
    (gate threshold 0.6 in the template vs 0.5 in code).

    Checks the DECLARED defaults (Settings.model_fields), not a live Settings(): a dev
    box's backend/.env and the JEVRAG_* vars the test session sets would otherwise mask
    the very drift this asserts on (and fake the parity of data_dir).
    """
    import re
    from pathlib import Path

    from app.config import Settings

    # The API key line is a placeholder, not a default — never cross-check it.
    SKIP = {"dashscope_api_key"}
    fields = Settings.model_fields
    template = (Path(__file__).resolve().parents[1] / ".env.example").read_text(
        encoding="utf-8")
    pairs = dict(re.findall(r"^(JEVRAG_[A-Z0-9_]+)=(.*)$", template, re.M))
    checked = 0
    drift = []
    for key, raw in pairs.items():
        field = key[len("JEVRAG_"):].lower()
        # ".env" files carry explanatory trailing comments (JEVRAG_DATA_DIR does);
        # python-dotenv drops them when it loads the file, so the check must too.
        declared = raw.split("#", 1)[0].strip()
        if field in SKIP or field not in fields or declared == "":
            continue
        actual = fields[field].default
        as_str = ("true" if actual is True else "false" if actual is False
                  else str(actual))
        if as_str != declared:
            drift.append(f"{key}: template={declared} code={as_str}")
        checked += 1
    assert not drift, "; ".join(drift)
    assert checked >= 30, f"only {checked} template values cross-checked — parser broken?"
