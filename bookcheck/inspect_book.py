"""Reading the structure of an e-book, whatever format it is in.

To say anything about whether a conversion preserved a book, both sides have to
be described in the same terms. This module reduces EPUB, MOBI, AZW3, and PDF
to one :class:`BookProfile`: title, author, chapter count, word count, image
count. Those five numbers are comparable across formats even though the file
layouts have nothing in common.

Each format is read directly rather than by shelling out to Calibre. EPUB is a
ZIP of XHTML, MOBI and AZW3 are PalmDB containers with a documented header, and
PDF is read through pypdf when it is installed. Parsing them here means the
verifier can explain a discrepancy in terms of what is actually inside the
file, and keeps the inspection honest about formats it cannot fully read.
"""

from __future__ import annotations

import re
import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# EPUB and MOBI both allow a lot of latitude in where metadata lives, so the
# patterns below are deliberately forgiving about namespaces and attributes.
DC_TITLE = re.compile(r"<dc:title[^>]*>(.*?)</dc:title>", re.S | re.I)
DC_CREATOR = re.compile(r"<dc:creator[^>]*>(.*?)</dc:creator>", re.S | re.I)
TAG = re.compile(r"<[^>]+>")
HEADING = re.compile(r"<h[1-3][^>]*>(.*?)</h[1-3]>", re.S | re.I)

TEXT_SUFFIXES = (".xhtml", ".html", ".htm")
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp")

#: Formats this module can describe structurally.
EPUB_FORMATS = (".epub",)
MOBI_FORMATS = (".mobi", ".azw", ".azw3", ".prc")
PDF_FORMATS = (".pdf",)
SUPPORTED = EPUB_FORMATS + MOBI_FORMATS + PDF_FORMATS


@dataclass
class BookProfile:
    """A format-independent description of one book."""

    path: str = ""
    format: str = ""
    title: Optional[str] = None
    author: Optional[str] = None
    chapters: int = 0
    words: int = 0
    images: int = 0
    documents: int = 0
    size_bytes: int = 0
    #: Whether the book declares its own navigation, as opposed to a chapter
    #: count inferred from headings. A book with eight headings and no TOC is
    #: not the same as one with an eight-entry TOC, and collapsing the two
    #: hides exactly the loss this tool exists to catch.
    has_toc: bool = False
    #: Anything the reader could not determine, so the verifier can decline to
    #: compare a field rather than report a false discrepancy.
    unavailable: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def has_text(self) -> bool:
        return self.words > 0

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "format": self.format,
            "title": self.title,
            "author": self.author,
            "chapters": self.chapters,
            "words": self.words,
            "images": self.images,
            "documents": self.documents,
            "has_toc": self.has_toc,
            "size_bytes": self.size_bytes,
            "unavailable": self.unavailable,
        }


def _strip_tags(markup: str) -> str:
    return TAG.sub(" ", markup)


def _readable(raw: bytes) -> Optional[str]:
    """Decode bytes to a title, or return None if they are not text.

    Binary offsets into e-book headers are a guess that sometimes lands in the
    middle of a struct. Returning the resulting mojibake as a title would make
    the verifier report a spurious "title changed" finding on every conversion,
    so anything that does not decode to mostly printable characters is treated
    as not found.
    """
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        try:
            text = raw.decode("latin-1")
        except UnicodeDecodeError:
            return None
    text = text.strip("\x00").strip()
    if not text:
        return None
    printable = sum(1 for ch in text if ch.isprintable())
    if printable < len(text) * 0.9:
        return None
    # MOBI writers substitute underscores for spaces in the PalmDB name.
    return re.sub(r"\s+", " ", text.replace("_", " ")).strip() or None


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    text = _strip_tags(value).strip()
    return re.sub(r"\s+", " ", text) or None


def inspect_epub(path: Path) -> BookProfile:
    """Describe an EPUB by reading its OPF, NCX, and XHTML documents."""
    profile = BookProfile(path=str(path), format="epub", size_bytes=path.stat().st_size)

    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()

        opf_names = [n for n in names if n.lower().endswith(".opf")]
        if opf_names:
            opf = archive.read(opf_names[0]).decode("utf-8", errors="replace")
            profile.title = _clean(m.group(1) if (m := DC_TITLE.search(opf)) else None)
            profile.author = _clean(m.group(1) if (m := DC_CREATOR.search(opf)) else None)
        else:
            profile.unavailable.append("metadata")

        text_docs = [n for n in names if n.lower().endswith(TEXT_SUFFIXES)]
        profile.documents = len(text_docs)
        profile.images = len([n for n in names if n.lower().endswith(IMAGE_SUFFIXES)])

        body = []
        headings = 0
        for name in text_docs:
            markup = archive.read(name).decode("utf-8", errors="replace")
            headings += len(HEADING.findall(markup))
            body.append(_strip_tags(markup))
        profile.words = len(" ".join(body).split())

        # An NCX or EPUB 3 nav document is the book's own statement of its
        # chapter structure, so prefer it over counting headings.
        ncx_names = [n for n in names if n.lower().endswith(".ncx")]
        if ncx_names:
            ncx = archive.read(ncx_names[0]).decode("utf-8", errors="replace")
            profile.chapters = ncx.count("<navPoint")
            profile.has_toc = profile.chapters > 0
        if not profile.chapters:
            nav = [n for n in names if "nav" in n.lower() and n.lower().endswith(TEXT_SUFFIXES)]
            if nav:
                markup = archive.read(nav[0]).decode("utf-8", errors="replace")
                profile.chapters = len(re.findall(r"<a\s[^>]*href=", markup, re.I))
                profile.has_toc = profile.chapters > 0
        if not profile.chapters:
            # Last resort: headings, then documents. Noted, because a heading
            # count and a declared TOC are not the same claim.
            profile.chapters = headings or len(text_docs)
            profile.notes.append("chapter count inferred; no TOC found")

    return profile


def _mobi_records(data: bytes) -> List[bytes]:
    """Split a PalmDB container into its records."""
    if len(data) < 78:
        return []
    count = struct.unpack(">H", data[76:78])[0]
    offsets = []
    for i in range(count):
        start = 78 + i * 8
        if start + 4 > len(data):
            break
        offsets.append(struct.unpack(">I", data[start : start + 4])[0])
    records = []
    for i, offset in enumerate(offsets):
        end = offsets[i + 1] if i + 1 < len(offsets) else len(data)
        if offset < len(data):
            records.append(data[offset:end])
    return records


def _exth_metadata(record0: bytes) -> dict:
    """Read the EXTH block, where MOBI keeps author and publisher."""
    result: dict = {}
    exth_start = record0.find(b"EXTH")
    if exth_start < 0 or exth_start + 12 > len(record0):
        return result
    count = struct.unpack(">I", record0[exth_start + 8 : exth_start + 12])[0]
    position = exth_start + 12
    # Record type 100 is author, 101 publisher, 103 description.
    wanted = {100: "author", 101: "publisher", 103: "description"}
    for _ in range(min(count, 200)):
        if position + 8 > len(record0):
            break
        rec_type, rec_len = struct.unpack(">II", record0[position : position + 8])
        if rec_len < 8 or position + rec_len > len(record0):
            break
        if rec_type in wanted:
            value = record0[position + 8 : position + rec_len]
            result.setdefault(
                wanted[rec_type], value.decode("utf-8", errors="replace").strip()
            )
        position += rec_len
    return result


def inspect_mobi(path: Path) -> BookProfile:
    """Describe a MOBI or AZW3 by reading its PalmDB and MOBI headers.

    Text is compressed inside the records, so word count is not recoverable
    without a full decompressor. That field is reported as unavailable rather
    than guessed, so the verifier skips it instead of inventing a discrepancy.
    """
    profile = BookProfile(
        path=str(path), format=path.suffix.lstrip(".").lower(), size_bytes=path.stat().st_size
    )
    data = path.read_bytes()
    records = _mobi_records(data)
    if not records:
        profile.unavailable.extend(["metadata", "words", "chapters", "images"])
        profile.notes.append("not a readable PalmDB container")
        return profile

    record0 = records[0]

    # The full title lives at an offset recorded in the MOBI header. Both the
    # offset (at MOBI+88) and the length (at MOBI+92) are relative to the start
    # of record 0, not to the MOBI header itself. Older MOBI writers disagree
    # about this in practice, so whatever comes back is validated as text
    # before it is trusted, and the PalmDB name is the fallback.
    mobi_start = record0.find(b"MOBI")
    if mobi_start >= 0 and mobi_start + 96 <= len(record0):
        try:
            title_offset, title_length = struct.unpack(
                ">II", record0[mobi_start + 88 : mobi_start + 96]
            )
            if 0 < title_length < 1024 and title_offset + title_length <= len(record0):
                profile.title = _readable(
                    record0[title_offset : title_offset + title_length]
                )
        except struct.error:
            pass
    if not profile.title:
        # PalmDB always carries a 32-byte name field, truncated but present.
        profile.title = _readable(data[:32].rstrip(b"\x00"))
    if not profile.title:
        profile.unavailable.append("title")
        profile.notes.append("no readable title in the MOBI or PalmDB headers")

    profile.author = _exth_metadata(record0).get("author")

    # Image records sit at the end of the record list and start with a
    # recognizable magic number, which is countable without decompressing.
    magic = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8")
    profile.images = sum(1 for r in records[1:] if r[:4].startswith(magic))

    profile.unavailable.extend(["words", "chapters"])
    profile.notes.append("MOBI text is compressed; word and chapter counts not read")
    return profile


def inspect_pdf(path: Path) -> BookProfile:
    """Describe a PDF using pypdf, if it is installed."""
    profile = BookProfile(path=str(path), format="pdf", size_bytes=path.stat().st_size)
    try:
        from pypdf import PdfReader  # noqa: PLC0415 - optional dependency
    except ImportError:
        profile.unavailable.extend(["metadata", "words", "chapters", "images"])
        profile.notes.append("pypdf not installed; PDF inspected by size only")
        return profile

    reader = PdfReader(str(path))
    profile.documents = len(reader.pages)

    metadata = reader.metadata or {}
    profile.title = _clean(str(metadata.get("/Title")) if metadata.get("/Title") else None)
    profile.author = _clean(str(metadata.get("/Author")) if metadata.get("/Author") else None)

    text_parts = []
    images = 0
    for page in reader.pages:
        try:
            text_parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - a damaged page should not sink the report
            continue
        try:
            images += len(page.images)
        except Exception:  # noqa: BLE001
            pass
    profile.words = len(" ".join(text_parts).split())
    profile.images = images

    # A PDF outline is the closest thing it has to a table of contents.
    try:
        def count_outline(items) -> int:
            total = 0
            for item in items:
                total += count_outline(item) if isinstance(item, list) else 1
            return total

        profile.chapters = count_outline(reader.outline)
        profile.has_toc = profile.chapters > 0
    except Exception:  # noqa: BLE001
        profile.unavailable.append("chapters")

    if not profile.chapters and "chapters" not in profile.unavailable:
        profile.notes.append("no PDF outline; the book has no navigable TOC")

    return profile


def inspect_book(path: str | Path) -> BookProfile:
    """Describe any supported e-book file."""
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"{target} does not exist")

    suffix = target.suffix.lower()
    if suffix in EPUB_FORMATS:
        return inspect_epub(target)
    if suffix in MOBI_FORMATS:
        return inspect_mobi(target)
    if suffix in PDF_FORMATS:
        return inspect_pdf(target)

    raise ValueError(
        f"{suffix or 'that file'} is not a format bookcheck can inspect; "
        f"supported: {', '.join(SUPPORTED)}"
    )
