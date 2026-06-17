import re
import unittest
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[2]
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def markdown_files():
    ignored_parts = {".git", ".venv", "__pycache__", ".pytest_cache"}
    for path in ROOT.rglob("*.md"):
        if ignored_parts.intersection(path.parts):
            continue
        yield path


def strip_code_fences(text):
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def relative_link_targets(markdown_path):
    text = strip_code_fences(markdown_path.read_text(encoding="utf-8"))
    for match in LINK_RE.finditer(text):
        raw_target = match.group(1).strip()
        if not raw_target or raw_target.startswith("#"):
            continue
        target = raw_target.split()[0]
        parsed = urlparse(target)
        if parsed.scheme or parsed.netloc:
            continue
        if target.startswith("mailto:"):
            continue
        yield raw_target, unquote(parsed.path)


class MarkdownLinkTest(unittest.TestCase):
    def test_relative_markdown_links_point_to_existing_files(self):
        missing = []
        for markdown_path in markdown_files():
            for raw_target, path_part in relative_link_targets(markdown_path):
                target_path = (markdown_path.parent / path_part).resolve()
                try:
                    target_path.relative_to(ROOT)
                except ValueError:
                    missing.append(f"{markdown_path.relative_to(ROOT)} -> {raw_target}")
                    continue
                if not target_path.exists():
                    missing.append(f"{markdown_path.relative_to(ROOT)} -> {raw_target}")

        self.assertEqual(missing, [], "\n".join(missing))


if __name__ == "__main__":
    unittest.main()
