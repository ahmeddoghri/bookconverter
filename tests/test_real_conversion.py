"""
Real end-to-end test that shells out to the actual Calibre ebook-convert
binary, the same way the app does in production. Skipped when Calibre isn't
installed on the runner (e.g. a lint-only CI job) instead of failing.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import book_converter_utils as bcu

EBOOK_CONVERT_PATH = bcu.find_ebook_convert_path()

pytestmark = pytest.mark.skipif(
    EBOOK_CONVERT_PATH is None,
    reason="Calibre's ebook-convert is not installed on this machine",
)


@pytest.fixture
def sample_txt(tmp_path):
    path = tmp_path / "sample.txt"
    path.write_text("Chapter 1\n\nThis is a real end-to-end conversion test.\n")
    return path


def test_txt_to_epub_to_pdf_round_trip(tmp_path, sample_txt):
    epub_path = str(tmp_path / "sample.epub")
    ok, result = bcu.convert_file_web(
        EBOOK_CONVERT_PATH, str(sample_txt), ".epub", str(tmp_path)
    )
    assert ok, result
    assert os.path.exists(result)
    assert os.path.getsize(result) > 0

    pdf_ok, pdf_result = bcu.convert_file_web(
        EBOOK_CONVERT_PATH, result, ".pdf", str(tmp_path)
    )
    assert pdf_ok, pdf_result
    with open(pdf_result, "rb") as f:
        header = f.read(5)
    assert header == b"%PDF-"
