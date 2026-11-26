"""Static checks that read the server's repository (`--repo PATH`), not the live endpoint."""

from __future__ import annotations

import itertools
import re
from pathlib import Path

from .report import Report

# "## [3.0.0] - 2026-11-26" or "## 3.0.0"; [Unreleased] and other headings are skipped.
_RELEASE = re.compile(r"^## \[?v?(\d+)\.(\d+)\.(\d+)\]?", re.MULTILINE)
_BREAKING = re.compile(r"^###.*\bBREAKING\b", re.MULTILINE | re.IGNORECASE)
_REMOVED = re.compile(r"^### Removed\b", re.MULTILINE)
_ADDED = re.compile(r"^### Added\b", re.MULTILINE)


def check_changelog(rep: Report, root: Path) -> None:
    """GTS-CORE-VER-03: each release step in CHANGELOG.md matches what its entry says changed.

    A `BREAKING` heading needs a MAJOR step (FAIL); `### Removed` outside a MAJOR step and
    `### Added` in a PATCH step are warnings, as those headings also cover changes outside the
    tool surface. Steps from a 0.x version are skipped: SemVer gives 0.x no stability.
    ponytail: trusts the changelog; it does not diff the tool surfaces of two releases.
    """
    rule = "GTS-CORE-VER-03"
    path = root / "CHANGELOG.md"
    if not path.is_file():
        rep.check("CHANGELOG.md exists", False, f"no CHANGELOG.md in {root}", rule=rule)
        return
    text = path.read_text(encoding="utf-8")
    heads = list(_RELEASE.finditer(text))
    steps = 0
    for head, older in itertools.pairwise(heads):
        new = tuple(map(int, head.groups()))
        old = tuple(map(int, older.groups()))
        if old[0] == 0:
            continue
        steps += 1
        body = text[head.end() : older.start()]
        step = f"{'.'.join(map(str, old))} → {'.'.join(map(str, new))}"
        major, minor = new[0] > old[0], new[:2] > old[:2]
        if _BREAKING.search(body) and not major:
            rep.check(f"{step}: a breaking change raises MAJOR", False, "it does not", rule=rule)
        elif _REMOVED.search(body) and not major:
            rep.warn(f"{step}: lists Removed", "a removed tool or parameter needs MAJOR", rule)
        elif _ADDED.search(body) and not minor:
            rep.warn(f"{step}: lists Added", "an additive change needs at least MINOR", rule)
    if steps:
        rep.check(f"{steps} release steps in CHANGELOG.md read", True, rule=rule)
    else:
        rep.skip("CHANGELOG.md", "no release step from 1.0.0 on", rule)
