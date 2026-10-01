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
    print(f"stats: {len(files)} markdown files, {lines} lines, README {readme}")
    for e in errors:
        print("ERROR:", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
