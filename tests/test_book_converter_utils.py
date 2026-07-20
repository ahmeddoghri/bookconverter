"""Unit tests for book_converter_utils.py."""
import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import book_converter_utils as bcu


def test_get_unique_filename_no_collision(tmp_path):
    out = bcu.get_unique_filename(str(tmp_path), "book", ".pdf")
    assert out == os.path.join(str(tmp_path), "book.pdf")


def test_get_unique_filename_appends_counter_on_collision(tmp_path):
    (tmp_path / "book.pdf").write_text("x")
    out = bcu.get_unique_filename(str(tmp_path), "book", ".pdf")
    assert out == os.path.join(str(tmp_path), "book (1).pdf")


def test_get_unique_filename_skips_multiple_collisions(tmp_path):
    (tmp_path / "book.pdf").write_text("x")
    (tmp_path / "book (1).pdf").write_text("x")
    out = bcu.get_unique_filename(str(tmp_path), "book", ".pdf")
    assert out == os.path.join(str(tmp_path), "book (2).pdf")


def test_get_unique_filename_normalizes_extension_without_dot(tmp_path):
    out = bcu.get_unique_filename(str(tmp_path), "book", "pdf")
    assert out.endswith(".pdf")


def test_find_ebook_convert_path_prefers_which(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ebook-convert")
    monkeypatch.setattr("os.path.exists", lambda p: True)
    monkeypatch.setattr("os.access", lambda p, mode: True)
    assert bcu.find_ebook_convert_path() == "/usr/bin/ebook-convert"


def test_find_ebook_convert_path_returns_none_when_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("os.path.exists", lambda p: False)
    assert bcu.find_ebook_convert_path() is None


def test_convert_file_web_without_configured_path():
    ok, msg = bcu.convert_file_web(None, "in.epub", ".pdf", "/tmp")
    assert ok is False
    assert "not configured" in msg


def test_convert_file_web_success(tmp_path):
    input_path = tmp_path / "in.epub"
    input_path.write_text("fake epub")

    mock_process = MagicMock()
    mock_process.communicate.return_value = (b"done", b"")
    mock_process.returncode = 0

    with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
        ok, out_path = bcu.convert_file_web(
            "/usr/bin/ebook-convert", str(input_path), ".pdf", str(tmp_path)
        )

    assert ok is True
    assert out_path.endswith("in.pdf")
    called_cmd = mock_popen.call_args[0][0]
    assert called_cmd[0] == "/usr/bin/ebook-convert"
    assert called_cmd[1] == str(input_path)


def test_convert_file_web_nonzero_exit_reports_stderr(tmp_path):
    input_path = tmp_path / "in.epub"
    input_path.write_text("fake epub")

    mock_process = MagicMock()
    mock_process.communicate.return_value = (b"", b"boom")
    mock_process.returncode = 1

    with patch("subprocess.Popen", return_value=mock_process):
        ok, msg = bcu.convert_file_web(
            "/usr/bin/ebook-convert", str(input_path), ".pdf", str(tmp_path)
        )

    assert ok is False
    assert "boom" in msg


def test_convert_file_web_timeout_kills_process(tmp_path):
    input_path = tmp_path / "in.epub"
    input_path.write_text("fake epub")

    mock_process = MagicMock()
    mock_process.communicate.side_effect = [
        subprocess.TimeoutExpired(cmd="ebook-convert", timeout=300),
        (b"", b""),
    ]

    with patch("subprocess.Popen", return_value=mock_process):
        ok, msg = bcu.convert_file_web(
            "/usr/bin/ebook-convert", str(input_path), ".pdf", str(tmp_path)
        )

    assert ok is False
    assert "timed out" in msg
    mock_process.kill.assert_called_once()
