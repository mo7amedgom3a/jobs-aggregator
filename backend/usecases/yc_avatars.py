"""Backfill founder avatars for already-crawled YC rows.

Usage:
    python3 -m usecases.yc_avatars
    python3 -m usecases.yc_avatars --limit 50 --delay 0.4
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill YC founder avatars.")
    parser.add_argument("--limit", type=int, default=0, help="Max companies to re-read (0 = all stored).")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between requests in seconds.")
    args = parser.parse_args(argv)

    from services.yc.avatars import backfill_avatars

    summary = backfill_avatars(max_companies=args.limit, delay=args.delay)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
