# End-user docs and README redesign — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the repo readable and trustworthy to someone who installs Jev-RAG and chats with their own documents — a docs hub, three end-user pages, a README whose every claim is traceable, and the small bind/CORS/gate-default fix that makes the privacy sentence true.

**Architecture:** Documentation becomes a user layer (hub → usage / configuration / troubleshooting) wrapped around the existing engineering docs without moving any of them; dev diaries relocate to `docs/dev/`. Three runtime changes back it: a loopback default host, a non-wildcard CORS origin, and one gate threshold aligned to its own documented value. A repo-wide markdown validator (extending the existing README one) is the test harness for every documentation task.

**Tech Stack:** Python 3.12 / FastAPI / pydantic-settings / pytest · Next.js 16 + TypeScript · bash + GitHub Actions · matplotlib + Playwright (preview card) · Markdown + Mermaid.

**Spec:** [docs/superpowers/specs/2026-10-01-end-user-docs-readme-design.md](../specs/2026-10-01-end-user-docs-readme-design.md) — this plan argues from that spec; read both.

## Global constraints

Every task implicitly satisfies these. Values are verbatim from the spec and `AGENTS.md`.

- All commands run inside WSL2: prefix with `wsl -d Ubuntu-24.04 -- bash -ic "…"`. Backend venv is `backend/.venv` (Python 3.12).
- **Never run `wsl … bash -ic` with inline loops or `$VAR` expansions from Git Bash** — they silently empty out. Write a script file, `tr -d '\r'` it, then run it.
- `scripts/*.sh` must stay LF (`​.gitattributes`) and must resolve the repo root from their own location — never hardcode absolute paths.
- Six `scripts/*.sh` files are **permanently phantom-dirty** (`git status` shows ` M` with empty `git diff`). Never `git add -A`. Stage named files and check `git diff --cached --name-only` before every commit.
- Push requires explicit user confirmation and must run from WSL (the SSH key lives in WSL root).
- `cd backend && .venv/bin/python -m pytest tests -v` and `bun run lint` must be green at every commit.
- Any change to a Jev knob or retrieval setting requires the bench smoke (`POST /api/bench/runs`, one scenario) with the delta versus `docs/benchmark-results.md` in the commit message.
- Any UI change requires live-browser verification. "It compiles" is not done.
- `backend/.env.example` must stay current with every config change, and its values must equal `app/config.py` defaults.
- No secrets in any committed file. API keys live only in `backend/.env` (gitignored).
- User-facing prose style: sentence-case headings, second person, contractions allowed, no links inside headings, alt text on every image.
- Forbidden claims in user-facing docs: `0 fabrications` as a headline, "hybrid is more correct", `~2 GB disk`, "Fully local stack" while a cloud call exists.
- Required disclosure wherever the README or `setup.md` describes privacy: the default bind is `127.0.0.1` and LAN access is an explicit opt-in.

## File structure

Create:

| Path | Responsibility |
| --- | --- |
| `docs/README.md` | Human hub — three lanes, one line per doc, "which page do I need" |
| `docs/usage.md` | Day-to-day tasks in the app, including known gaps |
| `docs/configuration.md` | Every setting, its real default, when to change it, what it costs |
| `docs/troubleshooting.md` | Symptom-first diagnostics; links to `setup.md` for install-level fixes |
| `docs/dev/AGENTS.md` | Child DOX for diaries: raw task log + dated snapshots, not contracts |
| `docs/dev/worklog.md` | moved from `worklog.md` |
| `docs/dev/project-status-2026-09-30.md` | moved from `docs/project-status-2026-09-30.md` |
| `.github/dependabot.yml` | npm · pip · github-actions, weekly |
| `.github/release.yml` | categorized auto-generated release notes |
| `.github/ISSUE_TEMPLATE/setup_problem.md` | "it won't install/run" routing to `troubleshooting.md` |
| `backend/tests/test_server_defaults.py` | loopback default, non-wildcard CORS, template↔code default parity |

Modify: `README.md` · `docs/AGENTS.md` · `AGENTS.md` · `backend/AGENTS.md` · `scripts/AGENTS.md` · `src/AGENTS.md` · `CHANGELOG.md` · `SECURITY.md` · `docs/setup.md` · `backend/app/config.py` · `backend/app/main.py` · `backend/.env.example` · `scripts/dev.sh` · `scripts/backend_service.sh` · `scripts/validate_readme.py` (renamed to `validate_docs.py`) · `.github/workflows/ci.yml` · `.github/ISSUE_TEMPLATE/config.yml` · `src/app/layout.tsx` · `src/app/page.tsx` · `scripts/render_social_preview.py` · `docs/jev-improvements-research.md` · `docs/windows-setup.md` · `docs/rag-upgrade-2026-results.md` · `backend/app/rag/crossenc.py` · `backend/scripts/run_testbench.py`

Delete (zero references anywhere): `docs/assets/img/escalation-gate.png` · `docs/assets/img/v3-architecture-diagram.png` · `docs/assets/img/v2-multistep.png` · `docs/assets/img/v2-trace-panel.png`

Unchanged paths (contract from the spec): every other file in `docs/`, all `docs/*.json` twins, `docs/assets/img/generate_diagrams.py`.

---

### Task 1: Repo-wide markdown validator (the test harness for everything below)

**Files:**
- Rename: `scripts/validate_readme.py` → `scripts/validate_docs.py`
- Modify: `scripts/validate_docs.py` (walk all markdown; per-file checks; fix the stale stats line)
- Modify: `.github/workflows/ci.yml` (add a `docs` job)
- Modify: `scripts/AGENTS.md:80` (ownership line)
- Modify: `docs/setup.md:97` (retarget the dead anchor this check newly surfaces, so CI lands green)

**Interfaces:**
- Produces: `python3 scripts/validate_docs.py` → exit 0 clean / exit 1 with `ERROR: <file>: <problem>` lines. Every later documentation task runs this as its test.

Why first: this file already implements link existence, image existence, GitHub anchor rules (lowercase, punctuation stripped, whitespace→hyphen, emoji leading-hyphen tolerance) and a secret scan — but only for `README.md`. A dead anchor already shipped (`docs/setup.md:97` → `README.md#configuration-backendenv`), so the generalization is the regression test for the whole plan. No new checker is added.

- [ ] **Step 1: Rename and confirm it still runs**

```bash
cd /mnt/d/test_jev/jev-rag && git mv scripts/validate_readme.py scripts/validate_docs.py
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag && python3 scripts/validate_docs.py"
```

Expected: prints its `stats:`/`lines:` lines and exits 0 (README is currently clean).

- [ ] **Step 2: Write the failing behavior — prove it currently misses non-README files**

Reproduce the known bug in a scratch file so the walk can be tested against a real defect:

```bash
printf '# t\nsee [setup](setup.md) and [anchor]README bad\n\n[a](README.md#configuration-backendenv)\n' > /tmp/probe.md
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag && ls docs/setup.md"
```

Expected: `docs/setup.md` exists, and `docs/setup.md:97` links `README.md#configuration-backendenv`, which resolves to no heading. The current script never looks at `docs/setup.md`, so it reports nothing — that is the gap.

- [ ] **Step 3: Generalize the walk**

Replace the fixed `readme = open('README.md').read()` section with a per-file loop, keeping the existing regexes and anchor function verbatim. Full replacement for the file:

```python
#!/usr/bin/env python3
"""Validate every Markdown file in the repo: links, images, anchors, details blocks,
and secret patterns. Exit 1 on any error, 0 otherwise."""
import os
import re
import subprocess
import sys
from pathlib import Path

# Repo root anchored from this file's own location (scripts/AGENTS.md
# machine-independent rule — never hardcode a checkout path).
REPO_ROOT = Path(__file__).resolve().parents[1]
os.chdir(REPO_ROOT)

SECRET_PATTERNS = ["sk-sp-", "github_pat_", "a1b32acc"]
ANCHOR_RE = re.compile(r"^#{1,6}\s+(.+)$", re.M)
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
MD_IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
HTML_IMG_RE = re.compile(r'<img\s+[^>]*src="([^"]+)"')
SKIP_ROOTS = ("node_modules/", ".next/", "vendor/", "models/", "backend/.venv/")


def github_anchor(heading: str) -> str:
    t = heading.strip().lower()
    t = re.sub(r"[^\w\s-]", "", t, flags=re.UNICODE)
    return re.sub(r"\s+", "-", t.strip())


def anchors_of(text: str) -> set[str]:
    out = set()
    for h in ANCHOR_RE.finditer(text):
        a = github_anchor(h.group(1))
        out.add(a)
        out.add(a.lstrip("-"))  # emoji headings: GitHub may drop the leading hyphen
    return out


def markdown_files() -> list[Path]:
    raw = subprocess.run(["git", "ls-files", "-z", "--", "*.md"],
                         capture_output=True, check=True).stdout.split(b"\0")
    files = [Path(p.decode()) for p in raw if p]
    return [f for f in files if not f.as_posix().startswith(SKIP_ROOTS)]


def resolve(source: Path, target: str) -> Path:
    """Relative link target resolved against the linking file's own directory."""
    if target.startswith("/"):
        return (REPO_ROOT / target.lstrip("/")).resolve()
    return ((REPO_ROOT / source).parent / target).resolve()


def check_file(path: Path, errors: list[str]) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.count("<details>") != text.count("</details>"):
        errors.append(f"{path}: <details> mismatch")
    if text.count("<summary>") != text.count("</summary>"):
        errors.append(f"{path}: <summary> mismatch")
    own = anchors_of(text)
    for src in MD_IMG_RE.findall(text) + HTML_IMG_RE.findall(text):
        if not src.startswith(("http://", "https://", "data:")):
            if not resolve(path, src.split("#")[0]).exists():
                errors.append(f"{path}: missing image {src}")
    for target in (m.group(2) for m in MD_LINK_RE.finditer(text)):
        target = target.strip().split(" ")[0]
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        file_part, _, frag = target.partition("#")
        if not file_part:
            if frag and frag not in own:
                errors.append(f"{path}: internal anchor #{frag} not found")
            continue
        if not resolve(path, file_part).exists():
            errors.append(f"{path}: broken link {target}")
            continue
        if frag and file_part.endswith(".md"):
            theirs = anchors_of(resolve(path, file_part).read_text(
                encoding="utf-8", errors="replace"))
            if frag not in theirs:
                errors.append(f"{path}: anchor #{frag} not found in {file_part}")
    for pat in SECRET_PATTERNS:
        if pat in text:
            errors.append(f"{path}: secret pattern {pat}")
    return text.count("\n") + 1


def main() -> int:
    errors: list[str] = []
    files = markdown_files()
    lines = sum(check_file(f, errors) for f in files)
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8").count("\n") + 1
    print(f"stats: {len(files)} markdown files, {lines} lines, README {readme}")
    for e in errors:
        print("ERROR:", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
```

Two deliberate choices to keep honest: `anchors_of` registers both the raw anchor and its leading-hyphen-stripped form (that is the emoji-heading tolerance carried over from the original script), and cross-file anchors are only checked for `.md` targets — non-markdown targets are existence-checked, nothing more.

- [ ] **Step 4: Run it and confirm it finds the real defect**

```bash
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag && python3 scripts/validate_docs.py"
```

Expected: exit 1 and at least `ERROR: docs/setup.md: anchor #configuration-backendenv not found in README.md`. Any *other* error it surfaces is a real finding — record each one; do not silence them with an allow-list. If it reports a false positive (a target that demonstrably renders on GitHub), fix the checker instead, and add the case to the note in step 6.

- [ ] **Step 4b: Land green — fix what it surfaces, in this commit**

A new always-red CI job is worse than no job, and `tests and lint stay green` is a repo
contract. So Task 1 must end with the validator exiting **0**. For each error it reports:

- Stale or dead relative path → correct it to the real target.
- Dead anchor whose correct target does not exist yet (this is the case for
  `docs/setup.md:97` → `README.md#configuration-backendenv`) → retarget it to a file that does
  exist, `backend/.env.example`, in this commit. Task 10 retargets it to
  `docs/configuration.md` once that page exists. Do not create a placeholder file to satisfy a
  link.
- A link that is correct but that the checker mis-parses → fix the checker, and note the case in
  Step 3's code so the reasoning survives.

Then re-run:

```bash
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag && python3 scripts/validate_docs.py"
```

Expected: exit 0, `stats:` line only.

- [ ] **Step 5: Add the CI job**

Append to `.github/workflows/ci.yml`, after the `frontend` job:

```yaml
  docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Validate markdown links, anchors, images and secrets
        run: python3 scripts/validate_docs.py
```

- [ ] **Step 6: Update the DOX line**

In `scripts/AGENTS.md`, replace the `validate_readme.py` bullet with:

```markdown
- `validate_docs.py` — repo-wide Markdown hygiene audit (every tracked `.md`): relative link
  and image existence, GitHub anchor rules (lowercase, punctuation stripped, spaces→hyphens,
  emoji leading-hyphen tolerance), `<details>` balance, secret-pattern scan. Exit 1 on any
  error. Run it before pushing any docs change — it is a CI job, not an optional check.
  Formerly README-only (`validate_readme.py`).
```

- [ ] **Step 7: Commit**

```bash
git add scripts/validate_docs.py .github/workflows/ci.yml scripts/AGENTS.md docs/setup.md
git commit -m "fix(docs): audit every markdown file for links, anchors and images

The README-only validator let a dead anchor ship in docs/setup.md:97 (points at
README.md#configuration-backendenv, which has never existed). Generalizing it to all
tracked markdown gives every later docs change a real test, and it now runs in CI. The
stale link retargets to backend/.env.example for now — the configuration reference lands
in a later commit and takes it from there."
```

---

### Task 2: `JEVRAG_HOST` and non-wildcard CORS

**Files:**
- Modify: `backend/app/config.py:166-169` (Server block)
- Modify: `backend/app/main.py:1-4,102-107,120-124`
- Modify: `backend/.env.example:86-88`
- Modify: `scripts/dev.sh:20-21`, `scripts/backend_service.sh:19`
- Test: `backend/tests/test_server_defaults.py` (create)

**Interfaces:**
- Produces: `Settings.host: str` (default `"127.0.0.1"`), `Settings.frontend_origin: str` (comma-separated raw string, default `"http://localhost:3000,http://127.0.0.1:3000"`), and `Settings.cors_origins -> list[str]` (parsed property used by `create_app`). The **env name** is `JEVRAG_FRONTEND_ORIGIN`; the **property** is `cors_origins` — Tasks 6 and 11 refer to the env name, Task 2's tests to the property. Task 3 and the README privacy section depend on these names.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_server_defaults.py`:

```python
"""Server defaults are a user-facing contract: the README claims local-first, so the
shipped default must bind loopback and must not accept any origin. Hermetic — no models,
no network. Run: cd backend && .venv/bin/python -m pytest tests -v"""
from __future__ import annotations

import os
import tempfile

import pytest

_TMP = tempfile.mkdtemp(prefix="jevrag-sd-")
os.environ.setdefault("JEVRAG_LAZY_MODELS", "1")
os.environ.setdefault("JEVRAG_DATA_DIR", _TMP)
os.environ.setdefault("JEVRAG_DASHSCOPE_API_KEY", "test-key")


def _fresh_settings(**overrides):
    from app.config import Settings, get_settings

    get_settings.cache_clear()
    for k, v in overrides.items():
        os.environ[f"JEVRAG_{k.upper()}"] = v
    s = Settings()
    get_settings.cache_clear()
    return s


def test_default_host_is_loopback():
    from app.config import Settings

    os.environ.pop("JEVRAG_HOST", None)
    assert Settings().host == "127.0.0.1"


def test_cors_never_allows_wildcard_by_default():
    from fastapi.middleware.cors import CORSMiddleware

    from app.main import create_app

    mw = [m for m in create_app().user_middleware if m.cls is CORSMiddleware]
    assert mw, "CORSMiddleware missing"
    assert "*" not in mw[0].kwargs["allow_origins"], mw[0].kwargs["allow_origins"]


def test_cors_origins_follow_env():
    s = _fresh_settings(frontend_origin="http://example.test:3000,http://localhost:3000")
    assert s.cors_origins == ["http://example.test:3000", "http://localhost:3000"]


@pytest.mark.xfail(reason="backend/.env.example declares JEVRAG_GATE_SCORE_THRESHOLD=0.6 "
                          "while app/config.py defaults to 0.5; removed in the next commit",
                   strict=True)
def test_env_example_defaults_match_code():
    """backend/AGENTS.md: template and code defaults must agree — they had drifted
    (gate threshold 0.6 in the template vs 0.5 in code)."""
    import re
    from pathlib import Path

    from app.config import Settings

    # The API key line is a placeholder, not a default — never cross-check it.
    SKIP = {"dashscope_api_key"}
    s = Settings()
    template = (Path(__file__).resolve().parents[1] / ".env.example").read_text(
        encoding="utf-8")
    pairs = dict(re.findall(r"^(JEVRAG_[A-Z0-9_]+)=(.*)$", template, re.M))
    checked = 0
    for key, raw in pairs.items():
        field = key[len("JEVRAG_"):].lower()
        if field in SKIP or not hasattr(s, field) or raw.strip() == "":
            continue
        declared = raw.strip()
        actual = getattr(s, field)
        as_str = ("true" if actual is True else "false" if actual is False
                  else str(actual))
        assert as_str == declared, f"{key}: template={declared} code={as_str}"
        checked += 1
    assert checked >= 30, f"only {checked} template values cross-checked — parser broken?"
```

- [ ] **Step 2: Run them to verify they fail**

```bash
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag/backend && .venv/bin/python -m pytest tests/test_server_defaults.py -v"
```

Expected: `test_default_host_is_loopback` FAIL with `AttributeError: 'Settings' object has no attribute 'host'`; the CORS test FAIL with `"*" not in ['*']`; the env-parity test report `xfailed` (its strict xfail marker is the tracked hand-off to Task 3). The first two are the failing tests this task exists to satisfy.

- [ ] **Step 3: Add the settings**

In `backend/app/config.py`, replace the Server block (`port`/`log_level`/`lazy_models`) with:

```python
    # --- Server ---
    # Bind address. Default loopback: this app has NO auth, so a 0.0.0.0 default
    # would hand anyone on the LAN the ability to read conversations, upload and
    # DELETE documents. Set JEVRAG_HOST=0.0.0.0 deliberately to share an instance.
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    # Comma-separated browser origins allowed to call the API. No wildcard: any web
    # page the user visits could otherwise drive (and wipe) the local backend.
    frontend_origin: str = "http://localhost:3000,http://127.0.0.1:3000"
    lazy_models: bool = False           # True: skip eager model loading at startup (tests)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_origin.split(",") if o.strip()]
```

The `@property` goes **inside the `Settings` class** — do not dedent it out; `data_dir`/`chroma_dir` properties begin at `config.py:193` and this one may sit just before that block if cleaner.

- [ ] **Step 4: Wire CORS and the bind**

In `backend/app/main.py`:

```python
# line 3 docstring — no longer advertise 0.0.0.0:
"""FastAPI application entrypoint.

Run: cd backend && .venv/bin/python -m app.main   (host/port/log level come from backend/.env)
"""
```

replace the middleware block with:

```python
    settings = get_settings()
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

and replace `main.py:124` with:

```python
    uvicorn.run("app.main:app", host=settings.host, port=settings.port,
                log_level=settings.log_level.lower())
```

- [ ] **Step 5: Make the launch scripts honor one source of truth**

Both scripts currently hardcode `--host 0.0.0.0 --port 8000`, duplicating `main.py`. Delete the flags and launch through the module, so `backend/.env` alone decides:

`scripts/dev.sh:20-21`:

```bash
log "starting backend (uvicorn via app.main — host/port from backend/.env)"
( cd "$ROOT/backend" && exec .venv/bin/python -m app.main ) &
```

`scripts/backend_service.sh:19`:

```bash
exec "$BACKEND_DIR/.venv/bin/python" -m app.main
```

- [ ] **Step 6: Add both vars to the template**

In `backend/.env.example`, replace the `# Server` block with:

```ini
# Server
# Bind address. 127.0.0.1 keeps the (unauthenticated) API to this machine.
# Set 0.0.0.0 only when you deliberately want other devices on your network to
# reach it — they get full read/write access to documents and conversations.
JEVRAG_HOST=127.0.0.1
JEVRAG_PORT=8000
JEVRAG_LOG_LEVEL=INFO
# Browser origins allowed to call the API (comma-separated).
JEVRAG_FRONTEND_ORIGIN=http://localhost:3000,http://127.0.0.1:3000
```

- [ ] **Step 6b: Fix the one other drift the parity test will surface**

`JEVRAG_JEV_SCORER` is `./models/jev-style/build/jev-score` in the template but `""` in code
(`config.py:76`, where empty means "let the runtime look it up"). Change the **template**, not
the code — pinning the default to a build path would break anyone whose scorer lives elsewhere,
while an unset value keeps the runtime lookup working:

```ini
# Path to the jev-score binary. Leave unset to use the runtime's own lookup
# (models/jev-style/build/jev-score is where scripts/setup_local_models.sh puts it).
# JEVRAG_JEV_SCORER=/absolute/path/to/jev-score
```

- [ ] **Step 7: Run the tests**

```bash
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag/backend && .venv/bin/python -m pytest tests -v -k 'not bench'"
```

Expected: host, CORS and env-following tests PASS and `test_env_example_defaults_match_code` reports **1 xfailed** — the suite is green at this commit, which is the point of the strict marker. The xfail must fail on exactly one line, `JEVRAG_GATE_SCORE_THRESHOLD: template=0.6 code=0.5`; if the reason mentions any other variable, that is newly discovered drift, resolve it here (template follows code unless code is the wrong default, in which case say so in the commit message) so Task 3 has a single reason to exist.

- [ ] **Step 8: Prove it binds loopback for real**

```bash
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag && bash scripts/backend_service.sh > /tmp/bs.log 2>&1 & sleep 12; curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/system/health; ss -ltnp 2>/dev/null | grep ':8000' || true; pkill -f 'app.main' || true"
```

Expected: `200`, and `ss` shows `127.0.0.1:8000` — not `0.0.0.0:8000`. If `ss` is unavailable in this distro, `python3 -c "import socket;..."` connect attempt from the LAN IP is the fallback.

- [ ] **Step 9: Commit**

```bash
git add backend/app/config.py backend/app/main.py backend/.env.example scripts/dev.sh scripts/backend_service.sh backend/tests/test_server_defaults.py
git commit -m "fix(server): bind loopback by default and stop allowing every origin

The app has no auth at all, so the shipped 0.0.0.0 bind plus
allow_origins=[\"*\"] meant anyone on the user's network (or any page in their
browser) could read conversations and delete documents, while the README sold
'local-first, privacy-preserving'. JEVRAG_HOST defaults to 127.0.0.1, CORS takes the
frontend origin, and both launch scripts now defer to backend/.env instead of
duplicating the hardcode. ensure-backend spawns backend_service.sh and health-checks
127.0.0.1, so self-healing is unaffected."
```

---

### Task 3: Align the gate default with its documented operating point

**Files:**
- Modify: `backend/app/config.py:134`
- Modify: `backend/.env.example:53-54`
- Test: `backend/tests/test_server_defaults.py` (goes green)
- Modify: `docs/testbench-results-layer2-full9.md`, `docs/benchmark-results.md` (smoke delta note)

**Interfaces:**
- Consumes: `test_env_example_defaults_match_code` from Task 2.
- Produces: `Settings.gate_score_threshold == 0.6`, which `docs/configuration.md` (Task 6) documents as the shipped default.

- [ ] **Step 1: Change the default, and delete the xfail marker**

`backend/app/config.py:134` — the comment claims calibration the value does not reflect:

```python
    gate_score_threshold: float = 0.6    # Youden-J operating point on eval data (θ=0.6;
    # the published gate-calibration tables in docs/testbench-results-*.md are computed
    # here). Must equal JEVRAG_GATE_SCORE_THRESHOLD in backend/.env.example — a user who
    # skips the template currently gets a different gate than the docs describe.
```

Then remove the `@pytest.mark.xfail(...)` decorator from
`test_env_example_defaults_match_code` in `backend/tests/test_server_defaults.py`. It is
`strict=True`, so leaving it in makes this change **fail** with "XPASS" — the marker is the
hand-off, and the hand-off closes here.

- [ ] **Step 2: Drop the "placeholder" wording from the template**

`backend/.env.example:53-54`:

```ini
# Score threshold for the features gate (Youden-J operating point, θ = 0.6)
JEVRAG_GATE_SCORE_THRESHOLD=0.6
```

- [ ] **Step 3: Run the hermetic suite**

```bash
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag/backend && .venv/bin/python -m pytest tests -v"
```

Expected: all green with **zero xfailed**, including `test_env_example_defaults_match_code`, and `test_pipeline_v3.py` / `test_v2_pipeline.py` unaffected (they pass thresholds explicitly, not via the default — confirm by reading any failure before "fixing" it).

- [ ] **Step 4: Bench smoke — mandatory, this is a Jev gate knob**

Write the request body to a file instead of nesting quotes through `wsl bash -ic`.

`/tmp/smoke.json`:

```json
{ "scenario_ids": ["outofscope"], "label": "gate-default-0.6 smoke" }
```

```bash
wsl -d Ubuntu-24.04 -- bash -ic "tr -d '\r' < /tmp/smoke.json > /tmp/sm.json && cd /mnt/d/test_jev/jev-rag && bash scripts/backend_service.sh > /tmp/smoke.log 2>&1 & sleep 25; curl -s localhost:8000/api/system/health"
wsl -d Ubuntu-24.04 -- bash -ic "curl -s -X POST localhost:8000/api/bench/runs -H 'Content-Type: application/json' -d @/tmp/sm.json"
```

Expected: health `ok`, then a JSON body containing the new run id. **Paste that id into the
analysis command and the commit message** — do not leave `<run_id>` in either.

```bash
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag/backend && .venv/bin/python scripts/analyze_bench_run.py <paste-run-id>"
```

Expected: both arms complete with 0 error rows over 8 questions, and correctness/abstention within ±1 question of the `outofscope` rows recorded for run `bf05f585` in `docs/benchmark-results.md`. **n=8 is a smoke, not a finding** — it cannot show a delta this small; say so in the doc note. Stop the backend afterward (`pkill -f 'app.main'`).

- [ ] **Step 5: Record the delta where the repo keeps run history**

Append to `docs/benchmark-results.md`, in its existing short "run notes" area (not the generated tables), a dated entry: date, run id, `outofscope` only, both arms, correctness/abstention numbers, the change being `gate_score_threshold 0.5 → 0.6` for users who never copied `.env`, and the explicit statement that this smoke has no statistical power at n=8. Add the same one-paragraph note under the caveats of `docs/testbench-results-layer2-full9.md` so the published θ=0.6 tables and the shipped default agree in writing.

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/.env.example backend/tests/test_server_defaults.py docs/benchmark-results.md docs/testbench-results-layer2-full9.md
git commit -m "fix(jev): ship the gate at its documented θ=0.6

.env.example declared 0.6 while config.py defaulted 0.5, so anyone who skipped the
template ran a different, less-calibrated escalation gate than the published
calibration tables (which are computed at θ=0.6). Smoke on outofscope (8Q, run
<id>): both arms completed, 0 error rows, correctness and abstention matching the
recorded v2 baseline within one question — n=8 has no power for a delta this small,
so this is a do-no-harm check, not a finding."
```

`<id>` above is the only value in this plan that cannot be known until it happens — substitute the real run id from Step 4 before committing, and never leave an angle bracket in a pushed commit message.

---

### Task 4: Favicon and footer copy (UI)

**Files:**
- Modify: `src/app/layout.tsx:24-26`
- Modify: `src/app/page.tsx:195-198`

**Interfaces:** Consumes `public/logo.svg` (already in the repo). Produces nothing later tasks need.

- [ ] **Step 1: Serve the icon locally**

```tsx
  icons: {
    icon: "/logo.svg",
  },
```

The current value is `https://z-cdn.chatglm.cn/z-ai/static/logo.svg` — a third-party request from an app that advertises local-first.

- [ ] **Step 2: Make the footer say what is true**

```tsx
        <span>Jev-RAG · System One (local decisions) + System Two (cloud LLM)</span>
        <span className="hidden sm:inline">
          Retrieval, reranking and decisions run on your machine · one cloud call writes the answer
        </span>
```

"Fully local stack" contradicts the Cloud status dot on the same page.

- [ ] **Step 3: Lint**

```bash
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag && bun run lint"
```

Expected: clean.

- [ ] **Step 4: Live-browser check (mandatory for UI)**

Start `bash scripts/dev.sh`, open `http://localhost:3000`, and verify in the browser: the tab icon is the local logo, the footer line reads correctly at desktop width and does not wrap or overflow at 375 px, the status popover still opens, and the Network panel shows **no** request to `z-cdn.chatglm.cn`. Then click through Traditional, Hybrid and Compare with a document uploaded, and confirm nothing else changed. Record the observation (screenshot or written note) in the commit message.

- [ ] **Step 5: Commit**

```bash
git add src/app/layout.tsx src/app/page.tsx
git commit -m "fix(ui): local favicon, and footer that admits the cloud call"
```

---

### Task 5: Move the diaries to `docs/dev/`

**Files:**
- Move: `worklog.md` → `docs/dev/worklog.md`
- Move: `docs/project-status-2026-09-30.md` → `docs/dev/project-status-2026-09-30.md`
- Create: `docs/dev/AGENTS.md`
- Modify: `docs/jev-improvements-research.md:11,109,128,189` · `docs/windows-setup.md:380` · `docs/rag-upgrade-2026-results.md:90` · `CHANGELOG.md:10,59` · `AGENTS.md:92` · `backend/app/rag/crossenc.py:19` · `backend/scripts/run_testbench.py:160` · the two moved files' own links

**Interfaces:** Produces `docs/dev/` as the canonical location for append-only records; every later task links diaries from here.

- [ ] **Step 1: Move both files**

```bash
mkdir -p docs/dev && git mv worklog.md docs/dev/worklog.md && git mv docs/project-status-2026-09-30.md docs/dev/project-status-2026-09-30.md
```

- [ ] **Step 2: Fix the moved files' own outbound links**

In `docs/dev/project-status-2026-09-30.md`: `](../worklog.md)` → `](worklog.md)`; every `](<doc>.md)` that refers to a durable doc becomes `](../<doc>.md)` (lines 9, 77, 79, 121, 138, 436 are the reference sites — re-grep rather than trusting the line numbers). In `docs/dev/worklog.md`, `docs/`-prefixed paths and `../`-prefixed links now resolve one level deeper: `](docs/x.md)` → `](../x.md)`, `](README.md)` → `](../README.md)`.

```bash
grep -n "](" docs/dev/project-status-2026-09-30.md | head -40
grep -n "](" docs/dev/worklog.md | head -40
```

- [ ] **Step 3: Fix every inbound reference**

```bash
grep -rn "worklog\.md\|project-status-2026-09-30" --include=*.md --include=*.py --include=*.ts --include=*.tsx . | grep -v "^./docs/dev/" | grep -v node_modules
```

Rewrite each hit to the new location (`docs/dev/worklog.md`, or `dev/worklog.md` from inside `docs/`; in Python/bash comments use the repo-root form). `AGENTS.md:92` mentions "the early worklog" in prose — no path change needed, confirm the sentence still reads true.

- [ ] **Step 4: Write the child DOX**

Create `docs/dev/AGENTS.md`:

```markdown
# Dev Log DOX

## Purpose

- Append-only engineering records: the per-task worklog and dated status snapshots.
  Raw detail for maintainers and agents — not end-user documentation.

## Ownership

- `worklog.md` — chronological per-task log (findings, dead ends, measured numbers with
  provenance). New entries append; never restate a durable contract here, link the doc.
- `project-status-2026-09-30.md` — dated status snapshot for the 2026-09-30 review.
  Frozen: correct as of that date, superseded by [../results.md](../results.md) and
  [../AGENTS.md](../AGENTS.md) afterwards. Do not update it in place.

## Local Contracts

- Nothing outside this folder may depend on a log entry as its source of truth — durable
  rules belong in the nearest owning doc (docs/AGENTS.md "stable contracts only").
- A dated snapshot is never rewritten; add a newer snapshot instead.

## Verification

- `python3 scripts/validate_docs.py` (links out of this folder must resolve)

## Child DOX Index

| Child | Scope |
| --- | --- |
| (none) | Two files |
```

- [ ] **Step 5: Index it in the parent**

In `docs/AGENTS.md` Ownership, add a line for `dev/` and update the Child DOX Index table from `(none) — Flat docs directory` to a row pointing at `dev/AGENTS.md`. Keep `worklog.md`'s absence from the durable-doc list explicit so nobody re-adds it.

- [ ] **Step 6: Validate and commit**

```bash
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag && python3 scripts/validate_docs.py"
git add docs/dev CHANGELOG.md AGENTS.md docs/AGENTS.md docs/jev-improvements-research.md docs/windows-setup.md docs/rag-upgrade-2026-results.md backend/app/rag/crossenc.py backend/scripts/run_testbench.py
git add -u worklog.md docs/project-status-2026-09-30.md
git diff --cached --name-only
git commit -m "docs: move the worklog and dated status snapshot out of the front door

A 948-line append-only log at repo root and a dated status doc in docs/ are the first
things an end user hits, and docs/AGENTS.md already says diaries are not durable docs.
They stay in git, under docs/dev/, with their own DOX and every link repaired."
```

The staged list must contain **no** `scripts/*.sh` entry — those six files are permanently
phantom-dirty and none of them belongs in this commit.

---

### Task 6: `docs/configuration.md`

**Files:**
- Create: `docs/configuration.md`

**Interfaces:** Consumes `Settings` field names/defaults from `backend/app/config.py` and the two new vars from Task 2, the corrected gate default from Task 3. Produces anchor names other pages link: `#required`, `#models`, `#retrieval`, `#hybrid-pipeline-and-escalation-gate`, `#memory-and-latency`, `#server-and-logging`, `#benchmarking`.

Content contract — every row must be copied from `config.py` (verified) rather than remembered. Required tables:

| Group | Variables (env name = default) |
| --- | --- |
| Required (2) | `JEVRAG_DASHSCOPE_BASE_URL` = `https://coding-intl.dashscope.aliyuncs.com/v1` · `JEVRAG_DASHSCOPE_API_KEY` = empty, **must** be set |
| Models | `JEVRAG_LLM_MODEL_DEFAULT` = `qwen3.7-plus` · `JEVRAG_LLM_MODEL_REASONING` = `qwen3.6-plus` · `JEVRAG_JEV_MODEL_DIR` = `./models/jev-style` · `JEVRAG_JEV_QUANT` = `Q4_K_M` · `JEVRAG_JEV_SCORER` = `""` (code) vs `./models/jev-style/build/jev-score` (template) · `JEVRAG_EMBED_MODEL` = `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` · `JEVRAG_RERANKER_MODEL` = `Xenova/ms-marco-MiniLM-L-6-v2` · `JEVRAG_BENCH_JUDGE_MODEL` = `kimi-k2.5` |
| Retrieval | `JEVRAG_TOP_K_RETRIEVE` = 10 · `JEVRAG_TOP_K_USE` = 4 · `JEVRAG_RETRIEVAL_MODE` = `hybrid_rrf` · `JEVRAG_RERANK_MODE` = `cross` · `JEVRAG_BM25_K1` = 1.5 · `JEVRAG_BM25_B` = 0.75 · `JEVRAG_RRF_K` = 60 · `JEVRAG_CHUNK_SIZE` = 900 · `JEVRAG_CHUNK_OVERLAP` = 140 · `JEVRAG_CONTEXTUAL_PREFIX` = true |
| Gate & slots | `JEVRAG_GATE_MODE` = `features` · `JEVRAG_GATE_SCORE_THRESHOLD` = **0.6** · `JEVRAG_HYBRID_EFFORT_ROUTING` = true · `JEVRAG_JEV_NO_RETRIEVAL_THRESHOLD` = 0.9 · `JEVRAG_HYBRID_MULTISTEP` = true · `JEVRAG_JEV_MULTISTEP_SUBQUERY_K` = 6 · `JEVRAG_JEV_MULTISTEP_MAX_POOL` = 12 · `JEVRAG_HYBRID_PASSAGE_BATTERY` = **false** · `JEVRAG_JEV_INJECTION_DROP_THRESHOLD` = 0.9 · `JEVRAG_JEV_CONTRADICTION_BLOCK_THRESHOLD` = 0.5 · `JEVRAG_JEV_EVIDENCE_DROP_THRESHOLD` = 0.1 · `JEVRAG_HYBRID_CORRECTIVE_RETRY` = true · `JEVRAG_HYBRID_BEST_OF_N` = true · `JEVRAG_HYBRID_CITATION_VERIFY` = true · `JEVRAG_JEV_CITATION_CONFIDENCE` = 0.8 · `JEVRAG_HYBRID_VERIFY_ANSWERS` = true · `JEVRAG_JEV_SUFFICIENCY_THRESHOLD` = 0.5 |
| Memory & latency | `JEVRAG_JEV_ENABLED` = true · `JEVRAG_JEV_DECISION_TIMEOUT` = 120.0 · `JEVRAG_JEV_SCORE_N_CTX` = 8192 · `JEVRAG_JEV_SCORE_N_SEQ_MAX` = 2 · `JEVRAG_JEV_SCORE_N_OUTPUTS_MAX` = 32 · `JEVRAG_JEV_SCORE_RLIMIT_DATA_MB` = 0 (empirically unusable) · `JEVRAG_JEV_RERANK_CHAR_LIMIT` = 400 · `JEVRAG_JEV_CONTEXT_CHAR_LIMIT` = 1600 · `JEVRAG_LLM_MIN_REQUEST_INTERVAL` = 0.0 (1.5 s on burst-limited gateways) · `JEVRAG_LAZY_MODELS` = false |
| Generation | `JEVRAG_LLM_TEMPERATURE` = 0.3 · `JEVRAG_LLM_MAX_TOKENS` = 2000 · `JEVRAG_LLM_DISABLE_THINKING` = true · `JEVRAG_DASHSCOPE_EXTRA_HEADERS` = `""` · `JEVRAG_DASHSCOPE_AUTH_CONFIG` = `""` |
| Server & storage | `JEVRAG_HOST` = `127.0.0.1` · `JEVRAG_PORT` = 8000 · `JEVRAG_LOG_LEVEL` = INFO · `JEVRAG_FRONTEND_ORIGIN` = `http://localhost:3000,http://127.0.0.1:3000` · `JEVRAG_DATA_DIR` = `./backend/data` · `JEVRAG_EMBED_CACHE_DIR` = `""` · `JEVRAG_RERANKER_CACHE_DIR` = `""` |
| Benchmarking | `JEVRAG_BENCH_PAIRWISE` = true · `JEVRAG_BENCH_CONTEXT_METRICS` = true · `JEVRAG_BENCH_MAX_QUESTIONS_PER_SCENARIO` = 0 · `JEVRAG_BENCH_JUDGE_ENSEMBLE` = `""` · `JEVRAG_BENCH_ROBUSTNESS_PARAPHRASES` = 0 |

- [ ] **Step 1: Verify every row against the code before writing it**

Write the dump to a file rather than inlining `python -c` through `wsl bash -ic` (nested quoting
through Git Bash is unreliable):

`/tmp/dump_settings.py`:

```python
import os, tempfile
os.environ.setdefault("JEVRAG_LAZY_MODELS", "1")
os.environ.setdefault("JEVRAG_DATA_DIR", tempfile.mkdtemp())
from app.config import Settings
for k, v in sorted(Settings.model_fields.items()):
    print(f"{k}={v.default!r}")
```

```bash
wsl -d Ubuntu-24.04 -- bash -ic "tr -d '\r' < /tmp/dump_settings.py > /tmp/ds.py && cd /mnt/d/test_jev/jev-rag/backend && .venv/bin/python /tmp/ds.py"
```

Expected: the authoritative default dump. Where the table above disagrees, the dump wins — fix the table, not the dump.

- [ ] **Step 2: Write the page**

Sections, in this order: opening contract (env-only, read once at startup, restart required, template is `backend/.env.example`, `JEVRAG_*` prefix, relative paths anchor to repo root not CWD) · "What you must set" (the two required vars + how to get a key) · one table per group above, each row `variable | default | what it does | change it when | cost / risk` · "Knobs not in the template" (every row in the tables above whose name does not appear in `.env.example`, with a note that adding them to the template is welcome) · "Model swaps" (embedding model must exist in fastembed's list; changing `JEVRAG_EMBED_MODEL` re-embeds everything — delete and re-upload; changing the judge model invalidates run-to-run comparability per `backend/AGENTS.md`) · "Cost display" (`LLM_PRICES_PER_MTOK` covers exactly `qwen3.7-plus` and `qwen3.6-plus`; any other generator shows `—` in the UI until you add a price, `config.py:26-32`) · "Who can reach this" (`JEVRAG_HOST` opt-in, no auth, one shared knowledge base) · "Internal fields you should not set" (`doc_ids`, `bench`, `escalate` — accepted by the endpoint but not part of the public chat surface, `docs/api.md`).

- [ ] **Step 3: State the drift you are closing**

Include a short "Known template drift" note for `JEVRAG_JEV_SCORER` (`""` in code vs a path in the template — harmless, template value is the built location) and record that `JEVRAG_GATE_SCORE_THRESHOLD` was 0.5 vs 0.6 until this change, so a reader with an old `.env` knows why.

- [ ] **Step 4: Validate**

```bash
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag && python3 scripts/validate_docs.py"
```

Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add docs/configuration.md
git commit -m "docs: configuration reference for the settings users actually touch

62 fields in app/config.py, 37 in backend/.env.example, and no page that listed either.
Every row is dumped from Settings, not remembered."
```

---

### Task 7: `docs/usage.md`

**Files:**
- Create: `docs/usage.md`

**Interfaces:** Consumes nothing from earlier tasks except the `configuration.md` anchors for cross-links. Produces `#add-documents`, `#ask-a-question`, `#choose-a-mode`, `#read-an-answer`, `#read-the-trace`, `#run-the-benchmark-lab`, `#known-gaps`.

- [ ] **Step 1: Write the page from the verified behaviors**

Every fact below is file-verified; include the file:line-free prose in the page but keep these as your source list.

- Extensions actually accepted (11): `.pdf .docx .xlsx .md .txt .html .htm .csv .json .xml .log` (`backend/app/rag/ingestion.py:23`). Note that the upload dropzone's own hint text advertises only 7 (`src/components/jevrag/sidebar.tsx:86`) and list the missing four — the hint is a UI bug, this page is the workaround.
- Limits: 25 MiB per file, 10 files per request (`backend/app/api/routes.py:28-29`); over-limit files come back as per-file errors instead of failing the request; no total corpus cap.
- Lifecycle: `processing → ready | error`, hover the red `error` to read the stored exception; a file with no extractable text is refused with "no extractable text found in the file"; originals are stored as `uploads/<uuid><ext>` and the filename lives only in SQLite.
- **There is no reindex.** Changing chunk size/overlap or the embedding model requires deleting and re-uploading (or removing `backend/data`). Documented reset: `rm -rf backend/data`.
- Asking: Enter sends, Shift+Enter newline; 1–8000 characters, over that is an HTTP 422 shown as a red box; follow-ups work but only the last 8 messages are replayed as history (`pipelines.py:928-950`); one global knowledge base — no per-document or per-chat scoping from the UI.
- Modes: Traditional = retrieve → rerank → one cloud call; Hybrid = adds effort routing, the score-feature escalation gate, sub-query decomposition, corrective retry, best-of-2 and citation verification; **Compare is two concurrent runs in the browser**, not a third pipeline (`store.ts:215-225`).
- Answer affordances: `[1]` chips are clickable and open the trace; groundedness badge is **hybrid-only**; quality badge = `0.4·answers_request + 0.4·citations_supported + 0.2·no_contradiction`; effort chip reads `no retrieval | single pass | multi-step`; the escalation decision appears in the trace card "Escalation gate (score features)" with `top1/top2/margin/mean` and the threshold, not in the bubble.
- Trace panel: six sections (System One decisions · best-of-2 candidates · retrieved passages · cited sources · System Two generation with model/latency/tokens/est. cost · timings) and the honest line that **it is not copyable** — the only clipboard action in the app is "Copy status JSON" in the status popover.
- Benchmark Lab: header → Benchmarks → tick scenario cards → "Run benchmark (N)"; 11 shipped scenarios (6 internal / 48 Q under `techdocs finance policy distractor multilingual outofscope`, 5 public / 98 Q under `squad hotpotqa triviaqa wiki2 musique`), all corpora committed, no downloads; one run at a time per process (HTTP 409); the dashboard cards and what each measures; delete is offered only on a completed run, so cancel is unreachable from the UI.
- Contamination warning, prominently: a lab run re-ingests its corpora (~779 committed `bench-*.md` files) through the same ingestor into the same Chroma collection (`runner.py:343-383`) and chat never filters `doc_ids`, so subsequent answers may cite the benchmark corpus. Recommend a separate `JEVRAG_DATA_DIR` for lab work, linking `configuration.md`.
- Known gaps (bulleted, no euphemisms): cannot stop a stream — the send button shows a stop glyph that is disabled and unwired (`chat-panel.tsx:209-214`) and mode tabs, the composer and history clicks all lock while streaming; no copy-answer; no export of results (CLI only); no bulk delete; no document preview; no conversation rename; no settings screen; conversation history is capped at the 100 newest with no pagination.
- Day-2: where logs go (backend stdout, `logs/backend.log` when self-spawned, `dev.log` for the frontend), and that a `JEV engine unavailable` error usually self-recovers because the subprocess reloads.

- [ ] **Step 2: Keep the voice right**

Sentence-case headings, second person, one task per heading, each heading starting with a base verb ("Add documents", not "Adding documents"). Every image gets alt text; no links inside headings.

- [ ] **Step 3: Validate**

```bash
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag && python3 scripts/validate_docs.py"
```

Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add docs/usage.md
git commit -m "docs: usage guide — the day-to-day page that did not exist

Nothing between 'open localhost:3000' and the API protocol described what a user can
actually do, including three things they otherwise discover the hard way: there is no
reindex, a Benchmark Lab run writes its corpora into your own knowledge base, and a
running stream cannot be stopped."
```

---

### Task 8: `docs/troubleshooting.md`

**Files:**
- Create: `docs/troubleshooting.md`

**Interfaces:** Consumes `docs/setup.md`'s existing 12-row troubleshooting table (link it, do not duplicate it) and `docs/setup-gpu.md`'s CUDA section. Produces `#it-wont-start`, `#uploads`, `#answers`, `#slow`, `#cost-shows-dash`, `#the-backend-died`, `#cant-reach-it-from-another-device`, `#collecting-diagnostics`.

- [ ] **Step 1: Write symptom → check → fix**

Symptom headings, each with a check and a fix, in user language:
- "It won't start" / "waking local models… forever" — the frontend self-spawns the backend and waits up to 150 s; check `logs/backend.log`; a first boot also downloads the ~225 MB embedding model.
- "Hybrid mode says the local Jev engine is unavailable" — `JEVRAG_JEV_MODEL_DIR`/scorer path, or the subprocess died; the engine auto-reloads, so retry once before digging.
- "My `.env` change did nothing" — settings are read once at startup; restart the backend.
- "Upload says no extractable text" / "N/M file(s) failed to index" — scanned-only PDFs, over-25 MiB files, >10 per request.
- "Answers cite `bench-*.md` files" — the Lab contaminated the corpus (link `usage.md`); delete those documents or use a separate data dir.
- "Answers are slow" — what dominates the ~41 s hybrid p50 (2 cores, CPU fallback, hard path); the escalation gate puts ~10 % of questions on the multi-step path; GPU is optional and ONNX falls back to CPU on WSL2.
- "Cost shows `—`" — the price table only knows the two shipped models (link `configuration.md`).
- "The backend was killed mid-run" — OOM; lower `JEVRAG_JEV_SCORE_N_CTX` / `_N_SEQ_MAX`; never remove the auto-reload path.
- "Can't reach it from another device" — the default bind is now `127.0.0.1`; set `JEVRAG_HOST=0.0.0.0` deliberately, and understand it is unauthenticated.
- "Frontend can't reach the backend" — must be on :8000, or set `JEVRAG_BACKEND_ORIGIN`.
- Install-level problems → link `docs/setup.md`'s troubleshooting table rather than restating it.

- [ ] **Step 2: Add the honest diagnostics ladder**

`Collecting diagnostics`: `/api/system/health` returns `{"status":"ok"}` unconditionally and checks **nothing** (`routes.py:220-222`) — so it proves the process is up, not the stack works. `GET /api/system/status` is the real one (LLM health + model list, jev `info()`, embeddings, retrieval, vector store, document counts, 10 config values); the status popover's "Copy status JSON" is the fastest way to get it into an issue. Then `bash scripts/probe_public_gateway.sh` (gate: `STATUS: SUCCESS`, exit 1 otherwise — do not start a bench run past a FAIL), then pytest, then a live smoke with a document from `scripts/test-assets/`. Note that the trace panel is not copyable, so screenshot it.

- [ ] **Step 3: Validate and commit**

```bash
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag && python3 scripts/validate_docs.py"
git add docs/troubleshooting.md
git commit -m "docs: symptom-first troubleshooting, including that /health proves nothing

The one endpoint the setup guide tells users to curl checks no database, no model and
no key, so 'ok' is not the diagnostic it looks like. /system/status is."
```

---

### Task 9: `docs/README.md` (the hub)

**Files:**
- Create: `docs/README.md`

**Interfaces:** Produces the canonical end-user entry point; Task 11 links it, Task 16 does not need to invent lane names because they are fixed: **Use it · Understand it · Measure it**.

- [ ] **Step 1: Write it**

```markdown
# Docs

Start here. Pick the lane that matches what you're trying to do.

## Use it

Install, then day-to-day.

1. [setup.md](setup.md) — fresh-machine install and verification (Windows: [windows-setup.md](windows-setup.md))
2. [usage.md](usage.md) — upload, ask, read citations, run the Benchmark Lab
3. [configuration.md](configuration.md) — every setting, its real default, and what it costs
4. [troubleshooting.md](troubleshooting.md) — stuck? start here, in symptom order

## Understand it

How it works, and why it works that way.

- [glossary.md](glossary.md) — the vocabulary (System One/Two, escalation gate, RRF, McNemar)
- [architecture.md](architecture.md) — components, data flow, deployment topology
- [hybrid-design.md](hybrid-design.md) — the decision pipeline and its configuration knobs
- [rag-upgrade-2026.md](rag-upgrade-2026.md) — why v3 gates on retrieval scores (research synthesis)
- [jev-improvements-research.md](jev-improvements-research.md) — decision patterns beyond model routing
- [api.md](api.md) — REST + SSE wire protocol
- [setup-gpu.md](setup-gpu.md) — CUDA on Linux and the WSL2 CPU fallback

## Measure it

Numbers, how they were produced, and how to reproduce them.

- [results.md](results.md) — the entry point: headline numbers, key findings, v1→v2→v3
- [benchmarking.md](benchmarking.md) — metric definitions, judge fairness protocol, statistics
- [testbench-design.md](testbench-design.md) — the pre-declared hypotheses and arms
- [testbench-results-layer1.md](testbench-results-layer1.md) — retrieval ablations
- [testbench-results-layer2-full9.md](testbench-results-layer2-full9.md) — the full 9-arm record
- [testbench-results-hgate.md](testbench-results-hgate.md) — the earlier 4-arm draw (reproducibility contrast)
- [benchmark-results.md](benchmark-results.md) — complete run history
- [benchmark-public.md](benchmark-public.md) · [benchmark-public-wave2.md](benchmark-public-wave2.md) · [benchmark-v2-ablation.md](benchmark-v2-ablation.md) · [rag-upgrade-2026-results.md](rag-upgrade-2026-results.md)
- [parallel-bench-runbook.md](parallel-bench-runbook.md) — multi-worker runs on a workstation

## Contribute

[CONTRIBUTING.md](../CONTRIBUTING.md) · [SECURITY.md](../SECURITY.md) · [CHANGELOG.md](../CHANGELOG.md) · [AGENTS.md](../AGENTS.md) (agent/dev contracts) · [dev/](dev/) (raw worklog and dated snapshots)
```

- [ ] **Step 2: Coverage check — every durable doc in exactly one lane**

Do **not** inline a loop with `$f` through `wsl bash -ic` from Git Bash: the variables silently
empty out (a known trap on this box). Write the probe to a file, strip CRs, then run it.

`/tmp/hub-coverage.sh`:

```bash
#!/usr/bin/env bash
set -uo pipefail
cd /mnt/d/test_jev/jev-rag
for f in docs/*.md; do
  b=$(basename "$f")
  [ "$b" = "README.md" ] && continue
  grep -q "](\?$b" docs/README.md && echo "in hub: $b" || echo "NOT IN HUB: $b"
done
```

```bash
wsl -d Ubuntu-24.04 -- bash -ic "tr -d '\r' < /tmp/hub-coverage.sh > /tmp/hc.sh && bash /tmp/hc.sh"
```

Expected: every `docs/*.md` prints `in hub:` except `AGENTS.md`, which is an agent contract and
deliberately not listed as a user doc (the hub points at `../AGENTS.md` instead). Adjust the hub
until nothing prints `NOT IN HUB`.

- [ ] **Step 3: Validate and commit**

```bash
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag && python3 scripts/validate_docs.py"
git add docs/README.md
git commit -m "docs: human hub for the docs tree

24 markdown files sat flat with no index a person could read — the only ordered view
was docs/AGENTS.md, which is an agent contract. Three lanes: use it, understand it,
measure it."
```

---

### Task 10: Make `docs/setup.md` accurate

**Files:**
- Modify: `docs/setup.md` (disk/time figures, GGUF size, the `:97` link, expected uvicorn output at `:149`, links to the new pages)

**Interfaces:** Consumes `configuration.md`/`troubleshooting.md` (created in Tasks 6 and 8). Produces the single install source the README points at.

- [ ] **Step 1: Fix the four numbers and one dead link**

- Disk: keep `~5 GB minimum / 8 GB comfortable` (`:33`) and make sure no other line says otherwise; state the breakdown once (venv ~1.5 GB, GGUF 0.53 GB, llama.cpp build ~2 GB, embedding cache ~0.3 GB).
- Duration: one figure. Use the measured/observed one — check both `:3` ("~15 min") and `:74` ("~10 minutes") and keep a single value with the qualifier "on a fast connection; the llama.cpp build dominates".
- GGUF: `0.53 GB (529,296,864 B)` — the exact byte count is what `setup_local_models.sh:70-79` verifies, so show it beside one readable rounding; remove the `~505 MB` variant.
- `:97` was parked on `backend/.env.example` by Task 1 (it used to point at the never-existing `README.md#configuration-backendenv`) → retarget it to [configuration.md](configuration.md), which now exists.
- `:149` tells users the expected output is `Uvicorn running on http://0.0.0.0:8000`. After Task 2 it is `http://127.0.0.1:8000`. Update it, and add one sentence on the LAN opt-in pointing at `configuration.md`.

- [ ] **Step 2: Point at the new pages instead of absorbing them**

At the end of the verification section, add: "Day 2: how to use the app is in [usage.md](usage.md); every knob is in [configuration.md](configuration.md); when something is wrong, [troubleshooting.md](troubleshooting.md)." Do **not** move the 12-row troubleshooting table — it stays the install-level reference.

- [ ] **Step 3: Verify commands still copy-paste**

Re-run the ladder in the page exactly as written (`curl …/api/system/health`, `bash scripts/probe_public_gateway.sh`, pytest, `bun run lint`). Any command that does not run verbatim is a defect in this task's scope — fix the page.

- [ ] **Step 4: Validate and commit**

```bash
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag && python3 scripts/validate_docs.py"
git add docs/setup.md
git commit -m "docs(setup): one disk figure, one time figure, one size spelling, live links

The guide contradicted the README on disk (2 GB vs 5 GB), itself on duration (10 vs 15
min), linked a README anchor that never existed, and taught users to expect a 0.0.0.0
bind that is no longer the default."
```

---

### Task 11: Rewrite `README.md`

**Files:**
- Modify: `README.md` (full rewrite)

**Interfaces:** Consumes every task above. Produces the anchors `docs/` links to; after this task the validator must be clean.

- [ ] **Step 1: Assemble in this order**

1. Banner `docs/assets/img/banner.svg` + one sentence.
2. Four functional badges: CI · license · backend · frontend. No `PRs welcome`, no `architecture: local-first`.
3. **What it does** — plain language, the 11 accepted extensions, two pipelines + Compare.
4. **Who it's for — and who it's not** — single user, one shared knowledge base, no multi-tenancy, one cloud call.
5. **Screenshots** — one hero (`chat-compare.png`), then a 2-up table of `trace-panel.png` and `bench-lab.png` and a third row with `bench-charts.png`. `chat-compare.png` appears exactly once.
6. **Requirements** — the table below, then quickstart commands (unchanged four), then `Open http://localhost:3000`.
7. **Which mode should I use** — table.
8. **How it works** — the shrunk mermaid, then two paragraphs (escalation gate; the 0.8B decision model), then links to `architecture.md` + `hybrid-design.md`.
9. **Results** — the honest panel.
10. **Privacy** — verbatim block below.
11. **Documentation** — the three lanes.
12. Contributing · Security · Credits · License.

No manual TOC or emoji link-ladder: GitHub auto-outlines the README, and emoji-heading anchors are a documented breakage source. Keep emoji in headings, but every anchor referenced from `docs/` or `CONTRIBUTING.md` must be verified by the validator.

- [ ] **Step 2: Use these exact claim-bearing strings**

Requirements table (from `docs/setup.md:29-33`, not invented):

```markdown
| | Minimum | Comfortable |
| --- | --- | --- |
| CPU | 2 cores | 4+ cores |
| RAM | 4 GB | 8 GB |
| Disk | ~5 GB | ~8 GB |
| OS | Linux, macOS, Windows via WSL2 | — |
| GPU | not required — jev-score uses CUDA when present; embedder and reranker fall back to CPU (ONNX Runtime does not support WSL2 GPU passthrough) | |

Local models total ~0.53 GB for the decision model plus ~225 MB for the embedder and
~91 MB for the reranker, downloaded on first use.
```

Mode table:

```markdown
| Mode | What runs | What you get | Rough latency |
| --- | --- | --- | --- |
| **Traditional** | hybrid retrieval → cross-encoder rerank → one cloud call | cited answer | ~20 s p50 measured on 2 cores |
| **Hybrid · Jev** | the above plus effort routing, an escalation gate, sub-query decomposition, corrective retry, best-of-2 and citation verification | cited answer + groundedness and quality badges + full decision trace | ~41 s p50, only on the ~10 % of questions that escalate |
| **Compare** | both of the above, concurrently, in one browser request pair | the two answers side by side | both at once |

Compare is not a third pipeline: the frontend runs the other two side by side
(`src/lib/jevrag/store.ts`). The groundedness badge only ever appears on hybrid
answers, because the traditional path does not run citation verification.
```

Mermaid (replace `README.md:78-146`; ≤15 lines, **no `%%{init…}%%` block and no `style` lines** so it follows the viewer's theme). `accTitle:` and `accDescr:` are directive **lines inside the block**, not `%%{…}%%` config keys ([mermaid accessibility](https://mermaid.ai/open-source/config/accessibility.html)) — and they are single-line strings:

````markdown
```mermaid
accTitle: Jev-RAG pipeline overview
accDescr: Documents are parsed, chunked and embedded into ChromaDB. A question is retrieved with BM25 and dense search, reranked, then gated: easy questions go straight to the cloud LLM for a cited answer; hard questions get a local decision model that decomposes, retries, picks the best of two candidates and verifies citations first.
flowchart LR
    D[Documents] --> P[parse + chunk + embed]
    P --> V[(ChromaDB<br/>dense + BM25)]
    Q[Question] --> R[retrieve + cross-encoder rerank]
    V --> R
    R --> F{escalation gate<br/>score features}
    F -->|easy| T[cloud LLM]
    F -->|hard ~10%| H[decompose -> retry -> best-of-2 -> citation check] --> T
    T --> S[stream + citations + trace]
    F -.decisions.-> J[local 0.8B model]
```
````

If GitHub renders the `accTitle`/`accDescr` lines as visible text rather than consuming them, delete them and keep the italic caption line below the diagram — do not leave a syntax artifact showing.

Fabrication line, verbatim (replaces `**0** fabrications`):

```markdown
Fabrication is only measured on the five unanswerable questions in the internal
`outofscope` scenario: 0/5 in the last two internal runs (v2 pipeline, runs `9d894b6c` and
`bf05f585`), after one draw measured 1/5 for a different reason (run `0314ac0a`). **The v3
pipeline has not had its fabrication rate published.** The public benchmark suites contain no
unanswerable questions, so no public run can produce this metric — see
[docs/benchmarking.md](docs/benchmarking.md).
```

Results panel: the two-column table from spec §4 (v3 headline `16814bd5` versus Layer-2 9-arm `36abefc6`) with the conditions line and the "a single Layer-2 draw is not a finding" sentence, then links to `docs/results.md`, `docs/benchmarking.md`, `docs/testbench-results-layer2-full9.md`.

Privacy section, verbatim:

```markdown
## Privacy: what stays local

Everything that touches your documents runs on your machine: parsing, chunking,
embeddings, the vector store, BM25, the reranker, the local decision model, and the
SQLite database. **One** call leaves your computer: the cloud LLM that writes the
answer, to the OpenAI-compatible endpoint in `backend/.env`.

The backend binds to `127.0.0.1` by default and has **no authentication**. Set
`JEVRAG_HOST=0.0.0.0` only if you deliberately want other devices on your network to
reach it — they get full read and write access to your documents and conversations.
CORS accepts only the frontend origin. There is no telemetry, no external vector DB and
no embedding API.
```

- [ ] **Step 3: Delete the indefensible claims**

Remove `**0** fabrications` from the top line, `~2 GB disk`, "Both pipelines use the 2026-standard retrieval stack" as a superiority claim, `What makes it different`'s assertion that the hybrid wins on hard questions (rewrite it as mechanism + cost, citing the null), and the duplicate `chat-compare.png` embed.

- [ ] **Step 4: Validate, and check the length budget**

```bash
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag && python3 scripts/validate_docs.py && wc -l README.md"
```

Expected: exit 0 and ≤200 lines. If the validator flags an anchor in a *later* task's file, that is Task 16's link sweep — fix the reference site.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs(readme): put the user before the evidence, and the caveat beside it

Reordered so a visitor learns what the app does and whether their machine qualifies
before meeting any number; requirements and a mode table added; the diagram no longer
forces a dark theme; chat-compare.png stopped appearing twice. The headline now shows
the v3 result next to the Layer-2 result that could not confirm it, and drops the
'0 fabrications' claim, which came from a run whose scenarios contain no unanswerable
questions at all."
```

---

### Task 12: Regenerate the social preview inside GitHub's cap

**Files:**
- Modify: `scripts/render_social_preview.py:6`
- Modify: `docs/assets/img/social-preview.png`
- Modify: `scripts/AGENTS.md:83` (the 1280×640 @2x line)

**Interfaces:** Consumes `scripts/social_preview.html` (unchanged source of truth for the card design).

- [ ] **Step 1: Anchor the output path and cut the scale**

Add `from pathlib import Path` if the module does not already import it, then replace the hardcoded `OUT = '/home/z/my-project/docs/assets/img/social-preview.png'` with:

```python
REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = str(REPO_ROOT / "docs" / "assets" / "img" / "social-preview.png")
```

and change the viewport/device-scale so the render is **1280×640 at 1×** — the current 2560×1280 @2x produces 1.07 MB, and GitHub requires the social preview to be under 1 MB (recommended 1280×640).

- [ ] **Step 2: Render**

```bash
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag && python3 scripts/render_social_preview.py"
```

Expected: the file written under `docs/assets/img/`, and the script prints its path. If Playwright/Chromium is absent, say so and stop — do not substitute an image-model artifact; this must be the repo's own renderer.

- [ ] **Step 3: Verify the cap**

`/tmp/check_preview.py`:

```python
import os
from PIL import Image
p = "docs/assets/img/social-preview.png"
im = Image.open(p)
print(im.size, round(os.path.getsize(p) / 1048576, 3), "MB")
```

```bash
wsl -d Ubuntu-24.04 -- bash -ic "tr -d '\r' < /tmp/check_preview.py > /tmp/cp.py && cd /mnt/d/test_jev/jev-rag && .venv/bin/python /tmp/cp.py 2>/dev/null || backend/.venv/bin/python /tmp/cp.py"
```

Expected: `(1280, 640)` and `< 1.0 MB`. If it exceeds 1 MB, re-render with PNG optimization or export JPEG — do not simply downscale the card.

- [ ] **Step 4: Update the DOX line and commit**

In `scripts/AGENTS.md`, change the `render_social_preview.py` bullet to name 1280×640 at 1× with the under-1 MB reason, and note that the card is uploaded through repo Settings (the REST endpoint is closed to PATs) — that is a manual step to flag to the user.

```bash
git add scripts/render_social_preview.py docs/assets/img/social-preview.png scripts/AGENTS.md
git commit -m "fix(scripts): render the social preview inside GitHub's 1 MB cap

The card was 2560x1280 at 1.07 MB — over the documented limit — and its generator
hardcoded a sandbox path, which the scripts DOX forbids."
```

---

### Task 13: Remove the dead diagram images

**Files:**
- Delete: `docs/assets/img/escalation-gate.png` · `docs/assets/img/v3-architecture-diagram.png` · `docs/assets/img/v2-multistep.png` · `docs/assets/img/v2-trace-panel.png`
- Modify: `docs/AGENTS.md:79-94` (the `assets/img/` ownership paragraph)

- [ ] **Step 1: Re-prove they are unreferenced**

```bash
for n in escalation-gate.png v3-architecture-diagram.png v2-multistep.png v2-trace-panel.png; do echo "== $n"; grep -rn --include=*.md --include=*.tsx --include=*.ts --include=*.py --include=*.html "$n" . --exclude-dir=node_modules --exclude-dir=.next --exclude-dir=vendor --exclude-dir=models || echo "  none"; done
```

Expected: zero hits for each **except** `escalation-gate-v2.png`-style matches caused by substring overlap — check the exact filename, and keep the `-v2` files. Note that `docs/AGENTS.md` names `v2-*.png` in prose; that line is edited in Step 3, not treated as a reference.

- [ ] **Step 2: Delete**

```bash
git rm docs/assets/img/escalation-gate.png docs/assets/img/v3-architecture-diagram.png docs/assets/img/v2-multistep.png docs/assets/img/v2-trace-panel.png
```

- [ ] **Step 3: Correct the ownership paragraph**

In `docs/AGENTS.md`, rewrite the `assets/img/` bullet so it lists only files that still exist: UI shots (`bench-lab.png`, `bench-charts.png`, `chat-compare.png`, `trace-panel.png`), the three `generate_diagrams.py` PNGs and their `.mmd`/`.svg` siblings, `layer2-arm-results.png`, `banner.svg`, `social-preview.png`. Keep every rule about provenance (illustrative literals are not evidence; `layer2-arm-results.png` is measured; UI shots come only from a live browser).

- [ ] **Step 4: Validate and commit**

```bash
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag && python3 scripts/validate_docs.py && du -sh docs/assets/img"
git add -A docs/assets/img docs/AGENTS.md
git commit -m "chore(assets): drop 3.9 MB of superseded diagram images

escalation-gate.png and v3-architecture-diagram.png are the pre-v2 renders of diagrams
that now exist as -v2 files; v2-multistep.png and v2-trace-panel.png were referenced by
nothing. 6.7 MB -> 2.8 MB."
```

`du` should read ~2.8 MB.

---

### Task 14: Community files

**Files:**
- Create: `.github/dependabot.yml` · `.github/release.yml` · `.github/ISSUE_TEMPLATE/setup_problem.md`
- Modify: `.github/ISSUE_TEMPLATE/config.yml`

**Interfaces:** None consumed; nothing later depends on these.

- [ ] **Step 1: Dependabot**

```yaml
version: 2
updates:
  - package-ecosystem: npm
    directory: "/"
    schedule: { interval: weekly }
    groups: { minor-and-patch: { patterns: ["*"] } }
  - package-ecosystem: pip
    directory: "/backend"
    schedule: { interval: weekly }
  - package-ecosystem: github-actions
    directory: "/"
    schedule: { interval: weekly }
```

- [ ] **Step 2: Release notes categories**

```yaml
changelog:
  categories:
    - title: Features
      labels: [feat, enhancement]
    - title: Fixes
      labels: [fix, bug]
    - title: Benchmarks and docs
      labels: [docs, bench]
    - title: Other
      labels: ["*"]
```

- [ ] **Step 3: Setup-problem template**

`.github/ISSUE_TEMPLATE/setup_problem.md`:

```markdown
---
name: 🧰 Setup or run problem
about: Installation, launch, upload or hybrid-mode failures
title: "[setup] "
labels: ["setup"]
---

**What you ran** (exact command)

**What you expected / what happened**

**OS and how you ran it** (native Linux / macOS / WSL2 Ubuntu-24.04)

**`GET /api/system/status` output** — open the status pill and press "Copy status JSON".
`/api/system/health` is not useful here: it answers `ok` without checking anything.

**Backend log tail** (`logs/backend.log`, or the uvicorn stdout in your terminal)

**Mode and scenario** (traditional / hybrid / compare; a benchmark run id if relevant)
```

- [ ] **Step 4: Update contact links**

In `.github/ISSUE_TEMPLATE/config.yml`, add two entries: `[docs] Usage and configuration` → `docs/README.md`, and `[troubleshooting] Common failures` → `docs/troubleshooting.md`. Keep the existing three, and update the setup-guide entry's URL text if it changes.

- [ ] **Step 5: Validate and commit**

```bash
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag && python3 scripts/validate_docs.py"
git add .github/dependabot.yml .github/release.yml .github/ISSUE_TEMPLATE
git commit -m "chore(github): dependabot, release-notes categories, setup-issue routing

All three are on GitHub's own maintainer checklist for 2026. No CODE_OF_CONDUCT.md and
no FUNDING.yml on purpose: neither is foregrounded by comparable local-LLM repos and
both are noise for a small research-leaning project."
```

---

### Task 15: `SECURITY.md` against the new default

**Files:**
- Modify: `SECURITY.md` (scope notes)

- [ ] **Step 1: Update the scope section**

Replace the "designed to run locally / not hardened for public exposure" bullets with the accurate state after Task 2: default bind `127.0.0.1`; no authentication exists, so `JEVRAG_HOST=0.0.0.0` is a deliberate trust decision that grants the whole network read/write access including document deletion; CORS allows only the configured frontend origin; cloud calls go only to the endpoint in `backend/.env`. Keep the leaked-credentials paragraph and the history-rewrite precedent verbatim.

- [ ] **Step 2: Commit, then tell the user the manual step**

```bash
git add SECURITY.md
git commit -m "docs(security): describe the loopback default, not the old wildcard CORS"
```

Then state plainly to the user: **private vulnerability reporting is a repo setting, not a file** — Settings → Security and insights → Enable "Report a vulnerability" — because `SECURITY.md:12` already directs reporters there.

---

### Task 16: DOX closeout and changelog

**Files:**
- Modify: `docs/AGENTS.md` · `AGENTS.md` · `backend/AGENTS.md` · `src/AGENTS.md` · `CHANGELOG.md`

- [ ] **Step 1: `docs/AGENTS.md`**

Add Ownership lines for `README.md` (the human hub — three lanes, every durable doc in exactly one), `usage.md`, `configuration.md`, `troubleshooting.md`, `dev/` (and its child index row), and `superpowers/` (dated design specs in `specs/` and their
implementation plans in `plans/`, one pair per brainstorm — agent artifacts, not user-facing). Update the `assets/img/` paragraph if Task 13 did not already. Add a Local Contract: "User-facing pages never restate install steps — `setup.md` owns them; `configuration.md` owns defaults and must equal `app/config.py`."

- [ ] **Step 2: root `AGENTS.md`**

In `## Development Environment`, correct the line that says ONNX Runtime falls back to CPU "because it doesn't support WSL2 GPU passthrough" only if the wording changed; leave the hardware facts. Update the Child DOX Index row for `docs/AGENTS.md` to say it now also owns the user layer and `docs/dev/`. Under `## Project-Wide Contracts`, add one bullet:

```markdown
- **Docs serve the user first.** `docs/README.md` is the human index; `usage.md`,
  `configuration.md` and `troubleshooting.md` are the end-user layer and must match code
  behavior, not aspiration. Claims in `README.md` and `docs/` carry a run id, a file:line,
  or a documented default — or they are stated as unmeasured. `python3
  scripts/validate_docs.py` runs in CI and gates every markdown link and anchor.
```

- [ ] **Step 3: `backend/AGENTS.md`**

Under Local Contracts, extend the env rule: adding a setting means `app/config.py` default + `backend/.env.example` + the `docs/configuration.md` row in the same commit, and `backend/tests/test_server_defaults.py` fails otherwise. Note the new `JEVRAG_HOST` / `JEVRAG_FRONTEND_ORIGIN` fields under the Server ownership line.

- [ ] **Step 4: `src/AGENTS.md`**

Record the local favicon and the corrected footer copy under Ownership (`app/layout.tsx`, `app/page.tsx`), and note that no user-facing copy may claim "fully local" while a cloud call exists.

- [ ] **Step 5: `CHANGELOG.md`**

Add one Unreleased section: the docs user layer, the README reorder and claim corrections, the bind/CORS/gate changes as behavior changes with their migration note (`JEVRAG_HOST=0.0.0.0` restores the old reachability), and the asset prune.

- [ ] **Step 6: Amend the spec where reality overruled it**

The spec proposed a new `scripts/check_docs_links.sh` (§11.1) and a `CODE_OF_CONDUCT.md` inside
its approved "Tidy" option (§9). Neither was built: the repo already had a markdown validator
(generalized and renamed in Task 1), and the conduct file was declined on evidence. Edit the
spec in place — delete the stale proposal, keep the reasoning one line — so the doc describing
this work matches the work.

- [ ] **Step 7: Validate and commit**

```bash
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag && python3 scripts/validate_docs.py"
git add AGENTS.md docs/AGENTS.md docs/dev/AGENTS.md backend/AGENTS.md src/AGENTS.md scripts/AGENTS.md CHANGELOG.md docs/superpowers/specs/2026-10-01-end-user-docs-readme-design.md
git commit -m "docs(dox): index the user layer and bind docs claims to evidence"
```

---

### Task 17: Full verification sweep

**Files:** none (verification only)

- [ ] **Step 1: Every gate, in order**

```bash
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag && python3 scripts/validate_docs.py"
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag/backend && .venv/bin/python -m pytest tests -v"
wsl -d Ubuntu-24.04 -- bash -ic "cd /mnt/d/test_jev/jev-rag && bun run lint"
```

Expected: validator exit 0; pytest all pass (report the count); lint clean.

- [ ] **Step 2: Prove the validator can say no**

Temporarily break one anchor in `docs/README.md`, run the validator, confirm exit 1 and the right message, then revert. A check that cannot fail is not a check.

- [ ] **Step 3: Live-browser pass**

`bash scripts/dev.sh`, then on `http://localhost:3000`: upload a file from `scripts/test-assets/`, ask in Traditional, Hybrid and Compare, confirm citations open the trace, confirm the groundedness badge appears only on hybrid, check the status popover copies, check the footer text and the local favicon, and check 375 px width for horizontal overflow. Confirm the Network panel shows no third-party icon request.

- [ ] **Step 4: Re-read for the forbidden list**

Search the tree for the claims that must not exist: `0 fabrications`, `~2 GB`, `Fully local stack`, `#configuration-backendenv`, `0.0.0.0:8000` as an *expected* output. All must be absent, or intentionally present in a historical record (`docs/dev/`, `CHANGELOG.md` past entries, `docs/rag-upgrade-2026-results.md`).

```bash
grep -rn "0 fabrications\|~2 GB\|Fully local stack\|configuration-backendenv" --include=*.md . | grep -v node_modules | grep -v docs/dev/
```

- [ ] **Step 5: Confirm the working tree, then ask about pushing**

```bash
git status --porcelain=v1
git log --oneline origin/main..HEAD
```

Expected: only the six phantom-dirty `scripts/*.sh` (with empty diffs) remain dirty. List the commits for the user and **ask before pushing**; push must run from WSL.

- [ ] **Step 6: Report against the spec's success criteria**

Quote each of the six criteria in spec §12 and state the evidence for it, including anything unproven (GitHub-side rendering of the social preview and the README outline are only confirmable after a push).

## Self-review notes

- **Spec coverage:** spec §1.1–1.9 → Tasks 9/7/11/11/10/1+10/2+15/5/12+13 respectively. §3 IA → Tasks 5–9. §4 README → Task 11. §5 pages → Tasks 6–9. §6 claims → Tasks 10–11. §7 behavior → Tasks 2–4. §8 visual → Tasks 11–13. §9 tidying → Tasks 5, 14, 15. §10 out-of-scope → not scheduled, by design. §11 gates → Task 17 (+ Task 1 for the checker). §12 criteria → Task 17 Step 6. No orphan requirements.
- **One spec amendment:** the spec proposed a new `scripts/check_docs_links.sh`. It is not needed — `scripts/validate_readme.py` already implements GitHub anchor rules and a secret scan, so Task 1 generalizes and renames it instead of adding a second checker. Task 16 Step 6 edits the spec so it matches what was built.
- **Green at every commit:** two obvious ordering traps were removed. Task 1 adds a CI job, so it also retargets the dead `docs/setup.md:97` link in the same commit (parked on `backend/.env.example`, then moved to `configuration.md` by Task 10) rather than landing a red job. Task 2 cannot satisfy template↔code parity until Task 3 changes the gate default, so the parity test carries a `strict=True` xfail that Task 3 is required to delete — the suite is green at both commits, and the hand-off cannot be silently skipped.
- **Naming:** `Settings.cors_origins` (list property) and `Settings.frontend_origin` (raw string) are distinct on purpose; Tasks 6 and 11 refer to the env name, Task 2's tests to the property.
- **Known unverifiable until pushed:** GitHub renders the social preview and the README outline server-side. Both are specified against GitHub's published rules here, and Task 17 Step 6 reports them as confirmed-or-not rather than assumed.
