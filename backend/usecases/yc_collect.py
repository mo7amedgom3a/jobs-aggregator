"""Manual CLI for the YC founder sourcing pipeline.

Examples
--------
    python3 -m usecases.yc_collect --batches "Spring 2026" --max-companies 5
    python3 -m usecases.yc_collect --skip-existing --no-emails
    python3 -m usecases.yc_collect --draft --batch "Spring 2026"
    python3 -m usecases.yc_collect --stats
"""

from __future__ import annotations

import argparse
import json
import sys

from repository.yc import YCRepository


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crawl YC companies/founders and manage outreach drafts.")
    parser.add_argument(
        "--batches",
        help='Comma-separated YC batch names, e.g. "Spring 2026,Winter 2026" (default: all configured).',
    )
    parser.add_argument("--max-companies", type=int, default=0, help="Cap companies per batch (0 = unlimited).")
    parser.add_argument("--max-pages", type=int, default=0, help="Cap directory pages per batch (0 = unlimited).")
    parser.add_argument("--skip-existing", action="store_true", help="Skip companies already in the database.")
    parser.add_argument("--no-emails", action="store_true", help="Disable company-website email discovery.")
    parser.add_argument("--draft", action="store_true", help="Generate outreach drafts after crawling.")
    parser.add_argument("--batch", help="Batch filter when drafting.")
    parser.add_argument("--channels", default="email,x,linkedin", help="Channels to draft for.")
    parser.add_argument("--limit", type=int, default=500, help="Max founders scanned when drafting.")
    parser.add_argument("--stats", action="store_true", help="Only print pipeline statistics.")
    args = parser.parse_args(argv)

    repository = YCRepository()
    repository.init_schema()

    if args.stats:
        print(json.dumps(repository.pipeline_stats(), indent=2))
        return 0

    from services.yc import collect_yc

    batches = [b.strip() for b in args.batches.split(",")] if args.batches else None
    summary = collect_yc(
        batches=batches,
        max_companies_per_batch=args.max_companies,
        max_pages_per_batch=args.max_pages,
        skip_existing=args.skip_existing,
        discover_emails=not args.no_emails,
    )
    print(json.dumps(summary, indent=2))

    if args.draft:
        from services.outreach import draft_outreach

        draft = draft_outreach(
            repository,
            channels=[c.strip() for c in args.channels.split(",") if c.strip()],
            batch=args.batch,
            limit=args.limit,
        )
        print(json.dumps(draft, indent=2))

    print(json.dumps(repository.pipeline_stats(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
