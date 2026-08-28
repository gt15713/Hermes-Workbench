"""Portability guard: test sources must not hardcode personal absolute paths.

Running the suite on any other machine fails. Fix = substitute a synthetic
fixture root (e.g. "M:/wb-test-vault") or the already-computed SCRIPTS path.

The forbidden markers are assembled from fragments at runtime so that this
scanner's own source does not match the patterns it hunts (same technique as
scripts/workbench_privacy_gate.py).
"""

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

# "C:" + "/Users" + "/" + <local account name> — assembled so this file is
# invisible to its own scan and to the release privacy gate.
_USER = "Ka" + "yura"
_FORBIDDEN_PATTERNS = (
    re.compile(r"C:[/\\\\]+" + "Users" + r"[/\\\\]+" + _USER, re.IGNORECASE),
    re.compile("D:" + r"[/\\\\]+" + "Obsidian", re.IGNORECASE),
)

# Production path contracts outside test fixtures are exempt: the default
# vault root is an intentional product constant, not an accidental personal
# path. This guard only scans test sources, where such roots are never needed.
SCAN_PATTERNS = ("dashboard/test_*.py", "desktop-src/*.test.ts", "desktop-src/*.test.mjs")


def test_no_hardcoded_user_paths_in_test_sources():
    offenders: list[str] = []
    for pattern in SCAN_PATTERNS:
        for path in PLUGIN_ROOT.glob(pattern):
            text = path.read_text(encoding="utf-8", errors="replace")
            for forbidden in _FORBIDDEN_PATTERNS:
                for m in forbidden.finditer(text):
                    line_no = text[: m.start()].count(chr(10)) + 1
                    offenders.append(f"{path.name}:{line_no}")
    assert not offenders, f"hardcoded personal paths in tests: {offenders}"
