"""Basic secret-pattern scan over repository files.

A pragmatic guard, not a guarantee: scans tracked and untracked
(non-ignored) text files for common secret patterns. Exits 1 on a hit.

Usage (from repository root):
    python tools/scan_secrets.py

Explicitly allowed: .env.example placeholder values (CHANGE_ME markers).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PATTERNS: list[tuple[str, str]] = [
    (r"gh[pousr]_[A-Za-z0-9]{20,}", "GitHub token"),
    (r"sk-[A-Za-z0-9]{20,}", "OpenAI-style API key"),
    (r"(?i)postgres(ql)?(\+asyncpg|\+psycopg)?://[^\s/:@]+:[^\s/@]+@", "DB URL with credentials"),
    (r"(?i)\b(password|passwd|secret|api_key|apikey|access_token|refresh_token)\b[\"']?\s*[:=]\s*[\"']?[^\s\"']{8,}", "assigned secret"),
    (r"(?i)\bpassword\s+'[^']{8,}'", "SQL password literal"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key id"),
    (r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", "private key material"),
]

# Files where these patterns appear as documentation of the scanner itself
# or as documented placeholders.
SELF_EXCLUDE = {Path("tools/scan_secrets.py").as_posix()}
PLACEHOLDER_MARKERS = (
    "CHANGE_ME",
    "CHANGE-ME",
    "<your",
    "example",
    "XXX",
    "BURAYA",
    "__GENERATED_PASSWORD__",
)
# Inline marker for lines that intentionally contain a fake secret fixture
# (synthetic values only, never real credentials). Accepts both Python
# ("# secret-scan-ok") and JS/TS ("// secret-scan-ok") comment styles.
LINE_ALLOW_RE = re.compile(r"(#|//)\s*secret-scan-ok")

# Compose-style variable references are not literal secrets. Expand them
# before matching: ${VAR:-default} keeps its default (a real secret hidden
# as a default is still caught), plain ${VAR} becomes empty.
DEFAULT_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*):-([^}]*)\}")
ANY_VAR_RE = re.compile(r"\$\{[^}]*\}")


def expand_vars(line: str) -> str:
    line = DEFAULT_VAR_RE.sub(lambda m: m.group(2), line)
    return ANY_VAR_RE.sub("", line)


def list_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


def looks_binary(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:4096]
    except OSError:
        return True
    return b"\x00" in chunk


def main() -> int:
    if not (REPO_ROOT / ".git").exists():
        print("not a git repository", file=sys.stderr)
        return 2

    findings: list[str] = []
    for rel in list_files():
        if rel in SELF_EXCLUDE:
            continue
        path = REPO_ROOT / rel
        if not path.is_file() or looks_binary(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if LINE_ALLOW_RE.search(line):
                continue
            if any(marker in line for marker in PLACEHOLDER_MARKERS):
                continue
            effective = expand_vars(line)
            for pattern, label in PATTERNS:
                if re.search(pattern, effective):
                    findings.append(f"{rel}:{lineno}: possible {label}: {line.strip()[:100]}")

    tracked = subprocess.run(
        ["git", "ls-files", "--cached"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    for forbidden in tracked:
        if forbidden == ".env" or (forbidden.startswith(".env") and not forbidden.endswith(".example")):
            findings.append(f"{forbidden}: env file is tracked in git")

    if findings:
        print("SECRET SCAN FAILED")
        for finding in findings:
            print("  " + finding)
        return 1
    print("secret scan: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
