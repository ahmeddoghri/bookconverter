"""Command line for inspecting, converting, and verifying e-books.

    bookcheck inspect book.epub
    bookcheck verify book.epub book.pdf
    bookcheck convert book.epub -t pdf --out ./converted
    bookcheck convert *.epub -t mobi --out ./kindle --min-fidelity 80
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .convert import convert, find_ebook_convert
from .inspect_book import SUPPORTED, inspect_book
from .verify import format_report, verify


def cmd_inspect(args: argparse.Namespace) -> int:
    profiles = [inspect_book(path) for path in args.books]
    if args.json:
        print(json.dumps([p.to_dict() for p in profiles], indent=2))
        return 0

    for profile in profiles:
        print(Path(profile.path).name)
        print(f"  format     {profile.format}")
        print(f"  title      {profile.title or '(none found)'}")
        print(f"  author     {profile.author or '(none found)'}")
        for label, key in (("chapters", "chapters"), ("words", "words"), ("images", "images")):
            value = "not readable" if key in profile.unavailable else getattr(profile, key)
            print(f"  {label:10} {value}")
        print(f"  size       {profile.size_bytes:,} bytes")
        for note in profile.notes:
            print(f"  note       {note}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    report = verify(args.source, args.output)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_report(report, verbose=args.verbose))

    if args.min_fidelity is not None and report.score < args.min_fidelity:
        print(
            f"\nFAIL: fidelity {report.score} is below --min-fidelity {args.min_fidelity}",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    if not find_ebook_convert():
        print(
            "error: ebook-convert not found. Install Calibre from "
            "https://calibre-ebook.com/download and ensure it is on your PATH.",
            file=sys.stderr,
        )
        return 2

    output_dir = Path(args.out)
    suffix = args.to if args.to.startswith(".") else f".{args.to}"
    failures = 0
    flagged = 0

    for source in args.books:
        source_path = Path(source)
        result = convert(
            source_path,
            output_dir / f"{source_path.stem}{suffix}",
            check_fidelity=not args.no_check,
        )

        if not result.ok:
            failures += 1
            print(f"FAIL  {source_path.name}: {result.error}", file=sys.stderr)
            continue

        score = result.fidelity_score
        label = f"{score}/100" if score is not None else "not checked"
        marker = "WARN" if result.needs_attention else "ok  "
        print(f"{marker}  {source_path.name} -> {result.output.name}  fidelity {label}")

        if result.report:
            for finding in result.report.critical + result.report.warnings:
                print(f"        {finding}")
        if result.needs_attention:
            flagged += 1
        if args.min_fidelity is not None and score is not None and score < args.min_fidelity:
            failures += 1

    if flagged:
        print(f"\n{flagged} file(s) converted but lost something worth checking.")
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bookcheck",
        description="Convert e-books and verify that the book survived.",
    )
    parser.add_argument("--version", action="version", version=f"bookcheck {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect_cmd = sub.add_parser("inspect", help=f"describe a book ({', '.join(SUPPORTED)})")
    inspect_cmd.add_argument("books", nargs="+")
    inspect_cmd.add_argument("--json", action="store_true")
    inspect_cmd.set_defaults(func=cmd_inspect)

    verify_cmd = sub.add_parser("verify", help="compare a source book against a converted one")
    verify_cmd.add_argument("source")
    verify_cmd.add_argument("output")
    verify_cmd.add_argument("--json", action="store_true")
    verify_cmd.add_argument("-v", "--verbose", action="store_true")
    verify_cmd.add_argument(
        "--min-fidelity", type=int, default=None,
        help="exit non-zero below this fidelity score",
    )
    verify_cmd.set_defaults(func=cmd_verify)

    convert_cmd = sub.add_parser("convert", help="convert books and verify each result")
    convert_cmd.add_argument("books", nargs="+")
    convert_cmd.add_argument("-t", "--to", required=True, help="target format, e.g. pdf")
    convert_cmd.add_argument("-o", "--out", default=".", help="output directory")
    convert_cmd.add_argument(
        "--no-check", action="store_true", help="skip the fidelity check"
    )
    convert_cmd.add_argument(
        "--min-fidelity", type=int, default=None,
        help="exit non-zero if any book falls below this score",
    )
    convert_cmd.set_defaults(func=cmd_convert)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
