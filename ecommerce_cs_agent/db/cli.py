from __future__ import annotations

import argparse
import json
import sys

from dataclasses import asdict

from ecommerce_cs_agent.db.migrations import apply_migrations, connection_from_environment


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ecommerce_cs_agent.db.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("migrate")

    args = parser.parse_args(argv)
    if args.command == "migrate":
        applied = apply_migrations(connection=connection_from_environment())
        print(json.dumps({"migrations": [asdict(item) for item in applied]}, ensure_ascii=False, default=str))
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
