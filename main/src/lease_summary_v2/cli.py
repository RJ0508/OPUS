"""Command-line interface for lease summary automation."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m lease_summary.cli",
        description="Generate an Opus lease summary from a PDF.",
    )
    parser.add_argument("--input", "-i", required=True, help="Path to lease PDF")
    parser.add_argument("--output", "-o", help="Output directory (default: data/output/)")
    parser.add_argument("--template", "-t", help="Path to blank Excel template")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress output")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}", file=sys.stderr)
        return 1

    from .pipeline import run

    results = run(
        input_pdf=input_path,
        output_dir=args.output,
        template_path=args.template,
    )

    if not args.quiet:
        summary = results["summary"]
        print(f"\n✓ Lease Summary Automation Complete")
        print(f"  Source:     {input_path.name}")
        print(f"  Pages:      {summary.document_meta.pages}")
        print(f"  Doc type:   {summary.document_meta.document_type}")
        print(f"  Confidence: {summary.overall_confidence:.1%}")
        print(f"  Flags:      {len(summary.review_flags)}")
        print(f"\n  Outputs:")
        print(f"    Excel:  {results['excel']}")
        print(f"    JSON:   {results['json']}")
        print(f"    Review: {results['review']}")

        if summary.review_flags:
            print(f"\n  Review flags:")
            for f in summary.review_flags:
                print(f"    [{f.flag}] {f.field}: {f.reason[:70]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
