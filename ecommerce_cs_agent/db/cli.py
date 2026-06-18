from __future__ import annotations

import argparse
import json
import sys

from dataclasses import asdict

from ecommerce_cs_agent.db.migrations import (
    DEFAULT_MIGRATIONS_DIR,
    apply_migrations,
    connection_from_environment,
    plan_migrations,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ecommerce_cs_agent.db.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    migrate_parser = subparsers.add_parser("migrate")
    migrate_parser.add_argument("--database-url")
    migrate_parser.add_argument("--migrations-dir", default=str(DEFAULT_MIGRATIONS_DIR))
    migrate_parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "migrate":
        if args.dry_run:
            applied = plan_migrations(args.migrations_dir, {})
        else:
            applied = apply_migrations(args.migrations_dir, connection=connection_from_environment(args.database_url))
        print(json.dumps({"migrations": [asdict(item) for item in applied]}, ensure_ascii=False, default=str))
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
