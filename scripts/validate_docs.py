#!/usr/bin/env python3
"""Documentation Markdown validator.

Audits *documentation* Markdown only — the repo-root pages (README, CHANGELOG, …),
everything under `docs/` and `.github/`, and every `AGENTS.md` (the DOX chain) anywhere
in the tree — for relative link and image existence, heading anchors (same-page `#frag`
and cross-file `page.md#frag`, checked against GitHub's own slug rule), `<details>`
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
# A link whose text is an image: `[![alt](badge.svg)](target)`. MD_LINK_RE stops at the
# first `]`, so it binds the *inner* `(badge.svg)` as the target and never sees the
# outer one — which is exactly where README.md:15 keeps its `#-how-it-works` anchor.
# Scan that shape explicitly so its target gets the same treatment as any other link.
MD_IMGLINK_RE = re.compile(r"\[!\[[^\]]*\]\(([^)]*)\)\]\(([^)]+)\)")
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
    """`text` with fenced blocks and inline code spans removed.

    Used for link, image and `<details>` detection only — see `anchor_source()` for
    why heading anchors must NOT be taken from this."""
    return INLINE_CODE_RE.sub("", FENCE_RE.sub("\n", text))


def anchor_source(text: str) -> str:
    """`text` with fenced blocks removed but inline code spans PRESERVED.

    This is what heading anchors are read from. GitHub builds a heading's id from the
    heading's rendered *text content*: an inline code span keeps its characters and
    loses only the backticks. `prose()` deletes the span outright, so for the real
    ``## Run `bf05f585` configuration (battery-off ablation)`` it would register
    `run--configuration-battery-off-ablation` — missing the id entirely and gaining a
    spurious double hyphen — which rejects a correct deep link and would accept a
    different wrong one. Verified against GitHub's own render of this repo
    (`GET /repos/…/contents/docs/benchmark-results.md`, Accept: application/vnd.github.html):
    the id it emits is `user-content-run-bf05f585-configuration-battery-off-ablation`.
    Fenced blocks still have to go: a `#` line inside a code sample is not a heading."""
    return FENCE_RE.sub("\n", text)


def github_anchor(heading: str) -> str:
    """GitHub's heading-id rule: lowercase, drop every character that is not a word
    character, a space or a hyphen, then turn **each** remaining space into a hyphen.

    No whitespace collapsing and no trimming, because GitHub does neither: `## 📸
    Screenshots` gets the id `-screenshots` (emoji dropped, the space that followed it
    survives as a leading hyphen), and ``## Run `0314ac0a` (archived: battery ON — the
    motivating negative result)`` gets
    `run-0314ac0a-archived-battery-on--the-motivating-negative-result` (the em dash is
    dropped, so its two spaces become two hyphens). Measured, not folklore: this rule
    reproduces 160 of the 161 heading ids GitHub itself emits for the 14 docs in scope
    (contents API with `Accept: application/vnd.github.html`).

    The one exception is deliberate: a heading whose emoji carries U+FE0F (a variation
    selector, e.g. `## 🏗️ Architecture`) gets an id that keeps that invisible mark,
    because JS word-class regexes keep Unicode marks and Python's `\\w` does not. Its
    real anchor therefore cannot be typed by hand — which is why
    `worklog.md:399` fixed such a link by swapping 🗂️ for 📁. The leading `.strip()`
    only mirrors Markdown's own trimming of heading-content whitespace."""
    t = heading.strip().lower()
    t = re.sub(r"[^\w\s-]", "", t, flags=re.UNICODE)
    return re.sub(r"\s", "-", t)


def anchors_of(text: str) -> set[str]:
    out = set()
    for h in ANCHOR_RE.finditer(text):
        a = github_anchor(h.group(1))
        out.add(a)
        # Deliberate leniency, not GitHub behaviour: GitHub *keeps* the leading hyphen
        # for an emoji heading, so `#screenshots` really does 404 while `#-screenshots`
        # works. Older pages in this repo (and hand-written TOCs) use the stripped form,
        # so accept both rather than fail the tree on a style question.
        out.add(a.lstrip("-"))
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


def read_doc(path: Path, errors: list[str]) -> str | None:
    """Read a Markdown file the tolerant way: undecodable bytes become U+FFFD, and a file
    that vanished (or is not readable) between `git ls-files` and now is reported as a
    finding. The tool's own contract is `ERROR: <file>: <problem>` + exit 1 — never a
    traceback that aborts the rest of the audit."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        errors.append(f"{path}: unreadable ({exc.strerror or exc.__class__.__name__})")
        return None


def check_file(path: Path, errors: list[str]) -> int:
    text = read_doc(path, errors)
    if text is None:
        return 0
    body = prose(text)
    if body.count("<details>") != body.count("</details>"):
        errors.append(f"{path}: <details> mismatch")
    if body.count("<summary>") != body.count("</summary>"):
        errors.append(f"{path}: <summary> mismatch")
    own = anchors_of(anchor_source(text))
    for src in MD_IMG_RE.findall(body) + HTML_IMG_RE.findall(body):
        if not src.startswith(("http://", "https://", "data:")):
            if not resolve(path, src.split("#")[0]).exists():
                errors.append(f"{path}: missing image {src}")
    link_targets = [m.group(2) for m in MD_LINK_RE.finditer(body)]
    link_targets += [m.group(2) for m in MD_IMGLINK_RE.finditer(body)]
    for target in link_targets:
        target = target.strip().split(" ")[0]
        if target.startswith(("http://", "https://", "mailto:")):
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
            theirs_src = read_doc(resolve(path, file_part), errors)
            if theirs_src is not None and frag not in anchors_of(anchor_source(theirs_src)):
                errors.append(f"{path}: anchor #{frag} not found in {file_part}")
    for pat in SECRET_PATTERNS:
        if pat in text:
            errors.append(f"{path}: secret pattern {pat}")
    return text.count("\n") + 1


def main() -> int:
    errors: list[str] = []
    files = markdown_files()
    lines = sum(check_file(f, errors) for f in files)
    # Totals only: every file audited here is already counted in `files`, and a README
    # special-case line had to re-read the file (unguarded, unlike every other read in
    # this script) for a number nobody acts on.
    print(f"stats: {len(files)} documentation markdown files, {lines} lines")
    for e in errors:
        print("ERROR:", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
