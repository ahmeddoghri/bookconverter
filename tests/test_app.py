"""Flask route tests for app.py, with the actual ebook-convert subprocess mocked out."""
import io
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module


def make_client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.app.config, "__setitem__", app_module.app.config.__setitem__)
    app_module.app.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")
    app_module.app.config["CONVERTED_FOLDER"] = str(tmp_path / "converted")
    os.makedirs(app_module.app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(app_module.app.config["CONVERTED_FOLDER"], exist_ok=True)
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def test_index_page_loads(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    resp = client.get("/")
    assert resp.status_code == 200


def test_allowed_file_matches_extension_and_source_format():
    assert app_module.allowed_file("book.epub", "epub") is True
    assert app_module.allowed_file("book.epub", "pdf") is False
    assert app_module.allowed_file("book.exe", "epub") is False
    assert app_module.allowed_file("book", "epub") is False


def test_upload_without_files_returns_400(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "EBOOK_CONVERT_PATH", "/usr/bin/ebook-convert")
    resp = client.post("/upload", data={"source_format": "epub", "target_format": "pdf"})
    assert resp.status_code == 400


def test_upload_without_ebook_convert_returns_500(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "EBOOK_CONVERT_PATH", None)
    data = {
        "source_format": "epub",
        "target_format": "pdf",
        "files[]": (io.BytesIO(b"fake epub bytes"), "book.epub"),
    }
    resp = client.post("/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 500


def test_upload_same_format_copies_file_without_converting(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "EBOOK_CONVERT_PATH", "/usr/bin/ebook-convert")
    data = {
        "source_format": "epub",
        "target_format": "epub",
        "files[]": (io.BytesIO(b"fake epub bytes"), "book.epub"),
    }
    with patch.object(app_module.bcu, "convert_file_web") as mock_convert:
        resp = client.post("/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["processed_files"]) == 1
    assert body["processed_files"][0]["converted_name"] == "book.epub"
    mock_convert.assert_not_called()


def test_upload_different_format_calls_converter(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "EBOOK_CONVERT_PATH", "/usr/bin/ebook-convert")
    data = {
        "source_format": "epub",
        "target_format": "pdf",
        "files[]": (io.BytesIO(b"fake epub bytes"), "book.epub"),
    }

    def fake_convert(ebook_convert_path, input_path, output_ext, out_dir, base_name=None):
        out_path = os.path.join(out_dir, f"{base_name}{output_ext}")
        with open(out_path, "wb") as f:
            f.write(b"fake pdf bytes")
        return True, out_path

    with patch.object(app_module.bcu, "convert_file_web", side_effect=fake_convert):
        resp = client.post("/upload", data=data, content_type="multipart/form-data")

    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["processed_files"]) == 1
    assert body["processed_files"][0]["converted_name"] == "book.pdf"
    assert body["errors"] == []


def test_upload_conversion_failure_is_reported_as_error(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "EBOOK_CONVERT_PATH", "/usr/bin/ebook-convert")
    data = {
        "source_format": "epub",
        "target_format": "pdf",
        "files[]": (io.BytesIO(b"fake epub bytes"), "book.epub"),
    }
    with patch.object(app_module.bcu, "convert_file_web", return_value=(False, "boom")):
        resp = client.post("/upload", data=data, content_type="multipart/form-data")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["processed_files"] == []
    assert any("boom" in e for e in body["errors"])


def test_download_nonexistent_file_returns_404(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    resp = client.get("/download/some-session/does-not-exist.pdf")
    assert resp.status_code == 404


def test_download_zip_with_no_session_returns_404(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    resp = client.get("/download_zip/does-not-exist")
    assert resp.status_code == 404


def test_full_round_trip_download(tmp_path, monkeypatch):
    """Upload -> convert (mocked) -> download the converted file."""
    client = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "EBOOK_CONVERT_PATH", "/usr/bin/ebook-convert")
    data = {
        "source_format": "epub",
        "target_format": "pdf",
        "files[]": (io.BytesIO(b"fake epub bytes"), "book.epub"),
    }

    def fake_convert(ebook_convert_path, input_path, output_ext, out_dir, base_name=None):
        out_path = os.path.join(out_dir, f"{base_name}{output_ext}")
        with open(out_path, "wb") as f:
            f.write(b"%PDF-1.4 fake pdf content")
        return True, out_path

    with patch.object(app_module.bcu, "convert_file_web", side_effect=fake_convert):
        upload_resp = client.post("/upload", data=data, content_type="multipart/form-data")

    body = upload_resp.get_json()
    download_url = body["processed_files"][0]["download_url"]

    download_resp = client.get(download_url)
    assert download_resp.status_code == 200
    assert download_resp.data.startswith(b"%PDF")
