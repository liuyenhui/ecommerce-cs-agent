#!/usr/bin/env python3
"""Check repository-local Markdown links."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


IGNORED_DIRS = {
    ".git",
    ".codegraph",
    ".venv",
    "__pycache__",
    "node_modules",
    "docs/vendor",
}
LINK_RE = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)")
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
HTML_ID_RE = re.compile(r"""(?:id|name)=["']([^"']+)["']""", re.IGNORECASE)


def is_ignored(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    parts = set(path.relative_to(root).parts)
    return any(rel == item or rel.startswith(f"{item}/") for item in IGNORED_DIRS) or bool(
        parts & {".git", ".codegraph", ".venv", "__pycache__", "node_modules"}
    )


def iter_markdown(root: Path):
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        dirs[:] = [
            item
            for item in dirs
            if not is_ignored(current_path / item, root)
        ]
        for name in files:
            path = current_path / name
            if path.suffix.lower() == ".md" and not is_ignored(path, root):
                yield path


def normalize_link(raw: str) -> str:
    link = raw.strip()
    if not link:
        return link
    if (link[0] == "<" and link.endswith(">")) or (
        link[0] in {"'", '"'} and link.endswith(link[0])
    ):
        link = link[1:-1].strip()
    return link


def should_skip(link: str) -> bool:
    lowered = link.lower()
    if lowered.startswith(("#", "http://", "https://", "mailto:", "tel:", "data:")):
        return True
    if "://" in lowered:
        return True
    return False


def slugify_heading(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = text.strip().lower()
    text = re.sub(r"[^\w\u4e00-\u9fff\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text.strip("-")


def anchors_for(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return set()

    anchors: set[str] = set()
    if path.suffix.lower() == ".md":
        used: dict[str, int] = {}
        for line in text.splitlines():
            match = HEADING_RE.match(line)
            if not match:
                continue
            slug = slugify_heading(match.group(2))
            if not slug:
                continue
            count = used.get(slug, 0)
            used[slug] = count + 1
            anchors.add(slug if count == 0 else f"{slug}-{count}")
    elif path.suffix.lower() in {".html", ".htm"}:
        anchors.update(HTML_ID_RE.findall(text))
    return anchors


def check_file(path: Path, root: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), 1):
        for match in LINK_RE.finditer(line):
            link = normalize_link(match.group(1))
            if should_skip(link):
                continue
            parsed = urlsplit(link)
            target_part = unquote(parsed.path)
            if not target_part:
                continue
            target = (path.parent / target_part).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                errors.append(f"{path.relative_to(root)}:{line_no}: link escapes repository: {link}")
                continue
            if not target.exists():
                errors.append(f"{path.relative_to(root)}:{line_no}: missing link target: {link}")
                continue
            if parsed.fragment and target.suffix.lower() in {".md", ".html", ".htm"}:
                fragment = unquote(parsed.fragment)
                if fragment and fragment not in anchors_for(target):
                    errors.append(
                        f"{path.relative_to(root)}:{line_no}: missing anchor #{fragment} in {target.relative_to(root)}"
                    )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Check repository-local Markdown links.")
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    errors: list[str] = []
    for path in iter_markdown(root):
        errors.extend(check_file(path, root))

    if errors:
        print("Markdown link check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"Markdown links ok under {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
