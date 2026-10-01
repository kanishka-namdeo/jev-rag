#!/usr/bin/env python3
"""Documentation Markdown validator.

Audits *documentation* Markdown only — the repo-root pages (README, CHANGELOG, …),
everything under `docs/` and `.github/`, and every `AGENTS.md` (the DOX chain) anywhere
in the tree — for relative link and image existence, GitHub anchor rules, `<details>`
balance and secret patterns. The benchmark corpora and the generated/vendored roots are
out of scope; see `NON_DOCUMENTATION_ROOTS`. Exit 1 on any error, 0 otherwise."""
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

# --- documentation scope -------------------------------------------------------
# This audit covers *documentation*, not every tracked `.md`. The 818 tracked Markdown
# files here are dominated by `backend/app/bench/corpora/**` (779 of them): ground-truth
# benchmark *documents* — i.e. test data, not prose. Auditing those would couple docs
# hygiene to benchmark content, and `backend/AGENTS.md` warns that editing a corpus
# document invalidates the questions that reference it, so a docs check has no business
# failing a corpus page or being held hostage by one. Documentation lives at the repo
# root, under `docs/`, under `.github/`, and in the `AGENTS.md` DOX chain anywhere.
DOCUMENTATION_DIRS = ("docs/", ".github/")   # durable doc trees
DOX_FILENAME = "AGENTS.md"                     # a DOX file is documentation wherever it sits

# The directory-scope EXCLUSION. One constant, so the reason survives: these roots are
# never documentation. `backend/app/bench/corpora/` is benchmark ground-truth test data
# (see the block above); the rest are the generated / vendored / local roots the root
# `AGENTS.md` lists as "intentionally unindexed". The exclusion WINS over the include, so
# an `AGENTS.md` under one of them (e.g. `skills/AGENTS.md`) is skipped too and the scope
# stays documentation-only as those trees grow. This is a path-prefix rule, NOT a
# per-file allow-list of link strings — nothing here names an individual document.
NON_DOCUMENTATION_ROOTS = (
    "backend/app/bench/corpora/",   # bench ground-truth documents = test data, not docs
    "node_modules/", ".next/", "backend/.venv/",
    "backend/data",                 # covers data/, data_merged/, data_par/
    "models/", "vendor/", "logs/", "mini-services/",
    "download/", "upload/", "skills/", ".zscripts/",
    "scripts/research/", "scripts/test-assets/",
)

# GitHub renders nothing inside a fenced block or an inline code span, so a `[x](y)`
# there is literal text, never a link, and a `<details>` there never opens a block.
# README-only scanning never hit this; the repo-wide walk does — the plan/spec docs
# under docs/superpowers/ quote example Markdown, and CHANGELOG/AGENTS mention
# `<details>` in backticks. Markup checks run on prose only; the secret scan stays
# on the raw text (credentials hide in code samples).
FENCE_RE = re.compile(r"^[ \t]*(?:`{3,}|~{3,}).*$\n(?:.*?$\n)*?[ \t]*(?:`{3,}|~{3,}).*$", re.M)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


def prose(text: str) -> str:
    """`text` with fenced blocks and inline code spans removed."""
    return INLINE_CODE_RE.sub("", FENCE_RE.sub("\n", text))


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


def is_documentation(path: Path) -> bool:
    """True when `path` (repo-relative) is documentation Markdown.

    In scope: repo-root `.md`, everything under `docs/` and `.github/`, and any
    `AGENTS.md`. Anything under `NON_DOCUMENTATION_ROOTS` — the benchmark corpora and
    the unindexed roots — is excluded, and that exclusion wins over the include."""
    posix = path.as_posix()
    if posix.startswith(NON_DOCUMENTATION_ROOTS):
        return False
    if posix.endswith(".md"):
        if "/" not in posix:                       # repo-root markdown (README.md, …)
            return True
        if posix.startswith(DOCUMENTATION_DIRS):    # docs/ and .github/
            return True
        if path.name == DOX_FILENAME:               # AGENTS.md anywhere in the tree
            return True
    return False


def markdown_files() -> list[Path]:
    raw = subprocess.run(["git", "ls-files", "-z", "--", "*.md"],
                         capture_output=True, check=True).stdout.split(b"\0")
    files = [Path(p.decode()) for p in raw if p]
    return [f for f in files if is_documentation(f)]


def resolve(source: Path, target: str) -> Path:
    """Relative link target resolved against the linking file's own directory."""
    if target.startswith("/"):
        return (REPO_ROOT / target.lstrip("/")).resolve()
    return ((REPO_ROOT / source).parent / target).resolve()


def check_file(path: Path, errors: list[str]) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    body = prose(text)
    if body.count("<details>") != body.count("</details>"):
        errors.append(f"{path}: <details> mismatch")
    if body.count("<summary>") != body.count("</summary>"):
        errors.append(f"{path}: <summary> mismatch")
    own = anchors_of(body)
    for src in MD_IMG_RE.findall(body) + HTML_IMG_RE.findall(body):
        if not src.startswith(("http://", "https://", "data:")):
            if not resolve(path, src.split("#")[0]).exists():
                errors.append(f"{path}: missing image {src}")
    for target in (m.group(2) for m in MD_LINK_RE.finditer(body)):
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
            theirs = anchors_of(prose(resolve(path, file_part).read_text(
                encoding="utf-8", errors="replace")))
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
    print(f"stats: {len(files)} documentation markdown files, {lines} lines, README {readme}")
    for e in errors:
        print("ERROR:", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
