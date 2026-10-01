#!/usr/bin/env python3
"""Validate README.md links, images, anchors, and details blocks."""
import re, os, sys
from pathlib import Path

# Repo root anchored from this file's own location — the old hardcoded sandbox path
# made this check unrunnable everywhere else (scripts/AGENTS.md machine-independent rule).
os.chdir(Path(__file__).resolve().parents[1])
readme = open('README.md').read()
errors, warnings = [], []

# 1. details/summary balance
opens = readme.count('<details>')
closes = readme.count('</details>')
if opens != closes:
    errors.append(f'<details> mismatch: {opens} open vs {closes} close')
if readme.count('<summary>') != readme.count('</summary>'):
    errors.append('<summary> mismatch')

# 2. images exist
for m in re.finditer(r'<img src="([^"]+)"', readme):
    if not os.path.exists(m.group(1)):
        errors.append(f'missing image: {m.group(1)}')

# 3. relative links exist (+ anchor check for docs)
link_pat = re.compile(r'\[([^\]]*)\]\(([^)]+)\)')
for m in link_pat.finditer(readme):
    text, target = m.group(1), m.group(2)
    if target.startswith(('http', '#', 'mailto')):
        continue
    path, _, frag = target.partition('#')
    if path and not os.path.exists(path):
        errors.append(f'broken link: {target}')
        continue
    if path and frag:
        content = open(path, encoding='utf-8').read()
        # github anchor: lowercase, strip emoji/punct, spaces->hyphens
        anchors = set()
        for h in re.finditer(r'^#{1,6}\s+(.+)$', content, re.M):
            t = h.group(1).strip().lower()
            t = re.sub(r'[^\w\s-]', '', t, flags=re.UNICODE)
            t = re.sub(r'\s+', '-', t.strip())
            anchors.add(t)
        if frag not in anchors:
            errors.append(f'anchor #{frag} not found in {path}')

# 4. internal README anchors (emoji headers -> github style)
anchors = set()
for h in re.finditer(r'^#{1,6}\s+(.+)$', readme, re.M):
    t = h.group(1).strip().lower()
    t = re.sub(r'[^\w\s-]', '', t, flags=re.UNICODE)
    t = re.sub(r'\s+', '-', t.strip())
    anchors.add(t)
for m in re.finditer(r'\]\(#([^)]+)\)', readme):
    if m.group(1) not in anchors:
        # GitHub strips leading hyphens from emoji headers in some cases; allow both
        alt = m.group(1).lstrip('-')
        if alt not in {a.lstrip('-') for a in anchors}:
            warnings.append(f'internal anchor #{m.group(1)} (have: {sorted(anchors)})')

# 5. secrets sanity
for pat in ['sk-sp-', 'github_pat_', 'a1b32acc']:
    for f in ['README.md', 'CONTRIBUTING.md', 'SECURITY.md', 'CHANGELOG.md',
              '.github/PULL_REQUEST_TEMPLATE.md',
              '.github/ISSUE_TEMPLATE/bug_report.md',
              '.github/ISSUE_TEMPLATE/feature_request.md',
              '.github/ISSUE_TEMPLATE/config.yml']:
        if pat in open(f).read():
            errors.append(f'secret pattern {pat} in {f}')

# 6. milestone commit links still intact
n_commits = len(re.findall(r'github.com/kanishka-namdeo/jev-rag/commit/', readme))
print(f'stats: {opens} details blocks, {n_commits} commit links, {len(anchors)} sections')
print(f'lines: {readme.count(chr(10))+1} (was 302)')
for e in errors: print('ERROR:', e)
for w in warnings: print('WARN:', w)
sys.exit(1 if errors else 0)
