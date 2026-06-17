#!/usr/bin/env python3
"""Validate local OpenAPI references without third-party Python packages."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


HTTP_METHODS = {
    "get",
    "put",
    "post",
    "delete",
    "options",
    "head",
    "patch",
    "trace",
}


def load_yaml_with_ruby(path: Path) -> Any:
    script = (
        "require 'yaml'; require 'json'; "
        "puts JSON.generate(YAML.load_file(ARGV.fetch(0)))"
    )
    try:
        result = subprocess.run(
            ["ruby", "-e", script, str(path)],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        raise RuntimeError("ruby is required to parse YAML in this check")
    if result.returncode != 0:
        detail = result.stderr.strip() or "YAML parse failed"
        raise RuntimeError(detail)
    return json.loads(result.stdout)


def iter_nodes(value: Any, path: str = "#"):
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from iter_nodes(child, f"{path}/{escape_json_pointer(str(key))}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_nodes(child, f"{path}/{index}")


def escape_json_pointer(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def unescape_json_pointer(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def resolve_pointer(document: Any, pointer: str) -> bool:
    if pointer == "#":
        return True
    if not pointer.startswith("#/"):
        return False
    current = document
    for raw_part in pointer[2:].split("/"):
        part = unescape_json_pointer(raw_part)
        if isinstance(current, dict):
            if part not in current:
                return False
            current = current[part]
        elif isinstance(current, list):
            if not part.isdigit():
                return False
            index = int(part)
            if index >= len(current):
                return False
            current = current[index]
        else:
            return False
    return True


def check_refs(document: Any) -> list[str]:
    errors: list[str] = []
    for path, value in iter_nodes(document):
        if isinstance(value, dict) and "$ref" in value:
            ref = value["$ref"]
            if not isinstance(ref, str):
                errors.append(f"{path}: $ref must be a string")
                continue
            if ref.startswith("#/") and not resolve_pointer(document, ref):
                errors.append(f"{path}: unresolved local $ref {ref}")
            elif ref.startswith("#") and not ref.startswith("#/") and ref != "#":
                errors.append(f"{path}: invalid local $ref {ref}")
    return errors


def check_operation_ids(document: Any) -> list[str]:
    errors: list[str] = []
    seen: dict[str, str] = {}
    paths = document.get("paths") if isinstance(document, dict) else None
    if not isinstance(paths, dict):
        return ["#: OpenAPI document must contain a paths object"]
    for route, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId")
            location = f"#/paths/{escape_json_pointer(str(route))}/{method}"
            if not isinstance(operation_id, str) or not operation_id:
                errors.append(f"{location}: missing operationId")
                continue
            if operation_id in seen:
                errors.append(
                    f"{location}: duplicate operationId {operation_id}; first seen at {seen[operation_id]}"
                )
            else:
                seen[operation_id] = location
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate docs/openapi.yaml local refs and operationId uniqueness."
    )
    parser.add_argument("openapi", nargs="?", default="docs/openapi.yaml")
    args = parser.parse_args()

    path = Path(args.openapi)
    if not path.is_file():
        print(f"OpenAPI file not found: {path}", file=sys.stderr)
        return 2

    try:
        document = load_yaml_with_ruby(path)
    except Exception as exc:
        print(f"Failed to load {path}: {exc}", file=sys.stderr)
        return 1

    errors = check_refs(document) + check_operation_ids(document)
    if errors:
        print(f"OpenAPI check failed for {path}:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"OpenAPI refs ok: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
