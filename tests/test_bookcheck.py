"""Tests for the fidelity inspector and verifier."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from bookcheck import inspect_book, verify
from bookcheck.convert import convert, find_ebook_convert
from bookcheck.fixtures import build_epub
from bookcheck.inspect_book import _readable, inspect_epub
from bookcheck.verify import compare, format_report

CALIBRE = find_ebook_convert()
needs_calibre = pytest.mark.skipif(CALIBRE is None, reason="Calibre is not installed")


@pytest.fixture
def book(tmp_path) -> Path:
    """A known-good EPUB: 5 chapters, 1 image, full metadata."""
    path = tmp_path / "book.epub"
    build_epub(path, chapters=5, images=2)
    return path


# --- inspection -------------------------------------------------------------

def test_epub_structure_matches_what_was_written(tmp_path):
    """Ground truth is known exactly, so the inspector can be checked against it."""
    path = tmp_path / "known.epub"
    truth = build_epub(path, chapters=7, images=3)
    profile = inspect_book(path)
    assert profile.chapters == truth["chapters"] == 7
    assert profile.documents == truth["documents"] == 7
    assert profile.images == truth["images"]


def test_epub_metadata_is_read(book):
    profile = inspect_book(book)
    assert profile.title == "The Fidelity Problem"
    assert profile.author == "Jordan Reyes"


def test_epub_word_count_is_plausible(book):
    profile = inspect_book(book)
    # 5 chapters x 7 paragraphs of roughly 20 words, plus headings.
    assert 500 < profile.words < 1500


def test_toc_presence_is_tracked_separately_from_chapter_count(tmp_path):
    """The distinction that makes a lost TOC detectable at all."""
    with_toc = tmp_path / "with.epub"
    without_toc = tmp_path / "without.epub"
    build_epub(with_toc, chapters=6)
    build_epub(without_toc, chapters=6, include_toc=False)

    a, b = inspect_book(with_toc), inspect_book(without_toc)
    assert a.has_toc and not b.has_toc
    # Both still report six chapters; only has_toc reveals the loss.
    assert a.chapters == b.chapters == 6


def test_missing_metadata_is_reported_as_absent(tmp_path):
    path = tmp_path / "anon.epub"
    build_epub(path, chapters=3, title=None, author=None)
    profile = inspect_book(path)
    assert profile.title is None
    assert profile.author is None


def test_unsupported_format_is_rejected(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello")
    with pytest.raises(ValueError, match="not a format"):
        inspect_book(path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        inspect_book(tmp_path / "absent.epub")


def test_readable_rejects_binary_noise():
    """Guards against reporting mojibake from a wrong header offset as a title."""
    assert _readable(b"The Fidelity Problem") == "The Fidelity Problem"
    assert _readable(b"\x1a\xff\x00\x02\x10\x00\x00") is None
    assert _readable(b"") is None


def test_readable_normalizes_mobi_underscores():
    assert _readable(b"The_Fidelity_Problem") == "The Fidelity Problem"


# --- verification -----------------------------------------------------------

def test_identical_books_lose_nothing(book):
    report = verify(book, book)
    assert report.score == 100
    assert report.ok
    assert report.findings == []


def test_lost_toc_is_detected(tmp_path):
    source, output = tmp_path / "a.epub", tmp_path / "b.epub"
    build_epub(source, chapters=6)
    build_epub(output, chapters=6, include_toc=False)
    checks = {f.check for f in verify(source, output).findings}
    assert "toc_lost" in checks


def test_lost_author_is_detected(tmp_path):
    source, output = tmp_path / "a.epub", tmp_path / "b.epub"
    build_epub(source, chapters=4)
    build_epub(output, chapters=4, author=None)
    assert "author_lost" in {f.check for f in verify(source, output).findings}


def test_lost_title_is_detected(tmp_path):
    source, output = tmp_path / "a.epub", tmp_path / "b.epub"
    build_epub(source, chapters=4)
    build_epub(output, chapters=4, title=None)
    assert "title_lost" in {f.check for f in verify(source, output).findings}


def test_lost_images_are_detected(tmp_path):
    source, output = tmp_path / "a.epub", tmp_path / "b.epub"
    build_epub(source, chapters=4, images=3)
    build_epub(output, chapters=4, images=0)
    assert "images_lost" in {f.check for f in verify(source, output).findings}


def test_heavy_text_loss_is_critical(book):
    source = inspect_book(book)
    damaged = inspect_book(book)
    damaged.words = int(source.words * 0.3)
    report = compare(source, damaged)
    assert report.critical
    assert report.critical[0].check == "text_lost"


def test_small_text_differences_are_tolerated(book):
    """Reflowing changes tokenization; a few percent must not raise an alarm."""
    source = inspect_book(book)
    reflowed = inspect_book(book)
    reflowed.words = int(source.words * 0.96)
    assert compare(source, reflowed).ok


def test_empty_output_is_critical(book):
    source = inspect_book(book)
    empty = inspect_book(book)
    empty.size_bytes = 0
    assert any(f.check == "empty_output" for f in compare(source, empty).critical)


def test_unavailable_fields_are_not_compared(book):
    """A format whose word count cannot be read must not produce a false finding."""
    source = inspect_book(book)
    output = inspect_book(book)
    output.words = 0
    output.unavailable.append("words")
    assert not any(f.check == "text_lost" for f in compare(source, output).findings)


def test_score_falls_as_severity_rises(book):
    source = inspect_book(book)
    damaged = inspect_book(book)
    damaged.author = None
    warned = compare(source, damaged).score

    broken = inspect_book(book)
    broken.words = 1
    assert compare(source, broken).score < warned < 100


def test_report_formats_readably(book):
    text = format_report(verify(book, book))
    assert "Fidelity score" in text
    assert "words" in text


def test_report_serializes(book):
    payload = verify(book, book).to_dict()
    assert payload["score"] == 100
    assert payload["source"]["title"] == "The Fidelity Problem"


# --- real conversions -------------------------------------------------------

@needs_calibre
@pytest.mark.parametrize("target", ["pdf", "mobi", "azw3", "epub"])
def test_real_conversion_preserves_the_book(book, tmp_path, target):
    """The regression that matters: a clean book must not trip a false alarm."""
    result = convert(book, tmp_path / f"out.{target}")
    assert result.ok, result.error
    assert result.report is not None
    assert result.fidelity_score == 100, [str(f) for f in result.report.findings]


@needs_calibre
def test_real_conversion_preserves_metadata(book, tmp_path):
    result = convert(book, tmp_path / "out.pdf")
    assert result.report.output.title == "The Fidelity Problem"
    assert result.report.output.author == "Jordan Reyes"


@needs_calibre
def test_mobi_title_survives_a_round_trip(book, tmp_path):
    """MOBI header offsets vary between writers; the fallback has to hold."""
    result = convert(book, tmp_path / "out.mobi")
    assert result.report.output.title == "The Fidelity Problem"


def test_conversion_of_a_missing_source_fails_cleanly(tmp_path):
    result = convert(tmp_path / "nope.epub", tmp_path / "out.pdf")
    assert not result.ok
    assert "does not exist" in result.error


def test_missing_calibre_is_reported_not_raised(book, tmp_path):
    result = convert(book, tmp_path / "out.pdf", ebook_convert="/nonexistent/ebook-convert")
    assert not result.ok
    assert result.error


@needs_calibre
def test_uncheckable_format_still_converts(book, tmp_path):
    """A format the inspector cannot read is not a failed conversion."""
    result = convert(book, tmp_path / "out.txt")
    assert result.ok
    assert result.fidelity_score is None


# --- CLI --------------------------------------------------------------------

def test_cli_inspect(book, capsys):
    from bookcheck.cli import main

    assert main(["inspect", str(book)]) == 0
    assert "The Fidelity Problem" in capsys.readouterr().out


def test_cli_verify(book, capsys):
    from bookcheck.cli import main

    assert main(["verify", str(book), str(book)]) == 0
    assert "Fidelity score" in capsys.readouterr().out


def test_cli_min_fidelity_gates(tmp_path):
    from bookcheck.cli import main

    source, output = tmp_path / "a.epub", tmp_path / "b.epub"
    build_epub(source, chapters=6, images=2)
    build_epub(output, chapters=6, images=0, author=None)
    assert main(["verify", str(source), str(output), "--min-fidelity", "95"]) == 1
    assert main(["verify", str(source), str(source), "--min-fidelity", "95"]) == 0


def test_cli_reports_unreadable_file(tmp_path, capsys):
    from bookcheck.cli import main

    bad = tmp_path / "book.txt"
    bad.write_text("not a book")
    assert main(["inspect", str(bad)]) == 2
