#!/usr/bin/env python3
"""Detect likely secrets without printing matched values."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


IGNORED_DIRS = {
    ".git",
    ".codegraph",
    ".venv",
    "__pycache__",
    "node_modules",
    "docs/vendor",
}
IGNORED_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz"}
PLACEHOLDER_RE = re.compile(
    r"^(|<[^>]+>|\$\{\{\s*secrets\.[A-Z0-9_]+\s*\}\}|"
    r"\$\{[A-Z0-9_]+\}|fake.*|example.*|changeme|redacted|test|test[-_].*)$",
    re.IGNORECASE,
)

TOKEN_PATTERNS = [
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\bgh[opsu]_[A-Za-z0-9_]{20,}\b")),
    ("private_key", re.compile(r"BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY")),
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
]
ASSIGNMENT_RE = re.compile(
    r"^\s*(?:export\s+)?("
    r"SMTP_PASSWORD|DATABASE_URL|LLM_API_KEY|SECRET_ACCESS_KEY|"
    r"JWT_SECRET|SESSION_SECRET|AGENT_API_TOKEN"
    r")\s*[:=]\s*([^\s#]+)"
)


def is_ignored(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    if path.suffix.lower() in IGNORED_SUFFIXES:
        return True
    return any(rel == item or rel.startswith(f"{item}/") for item in IGNORED_DIRS)


def iter_files(root: Path):
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        dirs[:] = [
            item
            for item in dirs
            if not is_ignored(current_path / item, root)
        ]
        for name in files:
            path = current_path / name
            if not is_ignored(path, root):
                yield path


def scan_file(path: Path, root: Path) -> list[str]:
    findings: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return findings

    for line_no, line in enumerate(text.splitlines(), 1):
        for name, pattern in TOKEN_PATTERNS:
            if pattern.search(line):
                if path.relative_to(root).as_posix() == "docs/security-local-files.md":
                    continue
                findings.append(f"{path.relative_to(root)}:{line_no}: {name}")
        for match in ASSIGNMENT_RE.finditer(line):
            raw_value = line.split("=", 1)[1] if "=" in line else match.group(2)
            value = raw_value.strip().strip("'\"")
            if "<from-secret>" in value or "<redacted>" in value:
                continue
            if "os.getenv" in line or "os.environ.get" in line or "${{" in line:
                continue
            if not PLACEHOLDER_RE.match(value):
                findings.append(f"{path.relative_to(root)}:{line_no}: {match.group(1).upper()}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan for likely secrets without printing values.")
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    findings: list[str] = []
    for path in iter_files(root):
        findings.extend(scan_file(path, root))

    if findings:
        print("Sensitive pattern check failed. Values are intentionally redacted.", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1

    print(f"Sensitive pattern scan ok under {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
