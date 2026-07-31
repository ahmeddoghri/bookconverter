"""Verify that an e-book conversion preserved the book.

``ebook-convert`` returning 0 means the process did not crash. Whether the
table of contents, the author's name, and chapter 12 survived are separate
questions, and this package answers them.

    >>> from bookcheck import verify
    >>> report = verify("book.epub", "book.pdf")
    >>> report.score, [str(f) for f in report.findings]
"""

from .inspect_book import BookProfile, inspect_book
from .verify import FidelityReport, Finding, compare, format_report, verify

__version__ = "1.1.0"

__all__ = [
    "BookProfile", "FidelityReport", "Finding",
    "compare", "format_report", "inspect_book", "verify",
]

from .convert import ConversionResult, convert, convert_many, find_ebook_convert  # noqa: E402

__all__ += ["ConversionResult", "convert", "convert_many", "find_ebook_convert"]
