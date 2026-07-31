"""Generated EPUBs with known structure, for testing the inspector.

Books are built from code rather than committed as binaries, so the corpus is
reproducible, carries no copyrighted text, and has counts that are known
exactly rather than measured after the fact.
"""

from __future__ import annotations

import base64
import zipfile
from pathlib import Path
from typing import Dict, List, Tuple

TITLE = "The Fidelity Problem"
AUTHOR = "Jordan Reyes"

# A 1x1 PNG, the smallest thing that still counts as an image.
PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

PARAGRAPHS_PER_CHAPTER = 7
WORDS_SENTENCE = (
    "This is paragraph {n} of chapter {c}, carrying enough words to make a "
    "conversion round trip measurable rather than a matter of opinion."
)


def _chapter_markup(index: int, image: bool = False) -> Tuple[str, str]:
    title = f"Chapter {index}: The Testing of Things"
    body = "\n".join(
        f"<p>{WORDS_SENTENCE.format(n=n, c=index)}</p>"
        for n in range(1, PARAGRAPHS_PER_CHAPTER + 1)
    )
    picture = '<p><img src="pixel.png" alt="figure"/></p>' if image else ""
    return title, (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
        f"<title>{title}</title></head><body>"
        f"<h1>{title}</h1>{picture}\n{body}</body></html>"
    )


def build_epub(
    path: str | Path,
    chapters: int = 5,
    images: int = 0,
    title: str | None = TITLE,
    author: str | None = AUTHOR,
    include_toc: bool = True,
) -> Dict[str, int]:
    """Write an EPUB with an exactly known structure.

    Returns the ground truth for what was written, so a test can assert the
    inspector reports the same thing rather than merely reporting something.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    documents: List[Tuple[str, str, str]] = []
    for index in range(1, chapters + 1):
        heading, markup = _chapter_markup(index, image=index <= images)
        documents.append((f"chap{index}.xhtml", heading, markup))

    manifest = "\n".join(
        f'<item id="c{i}" href="{name}" media-type="application/xhtml+xml"/>'
        for i, (name, _, _) in enumerate(documents, 1)
    )
    if images:
        manifest += '\n<item id="img" href="pixel.png" media-type="image/png"/>'
    if include_toc:
        manifest += '\n<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'

    spine = "\n".join(f'<itemref idref="c{i}"/>' for i in range(1, chapters + 1))

    metadata = [
        '<dc:identifier id="bookid">urn:uuid:bookcheck-fixture</dc:identifier>',
        "<dc:language>en</dc:language>",
    ]
    if title:
        metadata.insert(0, f"<dc:title>{title}</dc:title>")
    if author:
        metadata.insert(1, f"<dc:creator>{author}</dc:creator>")

    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" '
        'unique-identifier="bookid">\n'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        + "\n".join(metadata)
        + "\n</metadata>\n<manifest>\n"
        + manifest
        + '\n</manifest>\n<spine toc="ncx">\n'
        + spine
        + "\n</spine>\n</package>"
    )

    with zipfile.ZipFile(target, "w") as archive:
        # The mimetype entry must be first and stored uncompressed.
        archive.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        archive.writestr("content.opf", opf)
        if include_toc:
            navpoints = "\n".join(
                f'<navPoint id="n{i}" playOrder="{i}"><navLabel><text>{heading}</text>'
                f'</navLabel><content src="{name}"/></navPoint>'
                for i, (name, heading, _) in enumerate(documents, 1)
            )
            archive.writestr(
                "toc.ncx",
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
                '<head><meta name="dtb:uid" content="urn:uuid:bookcheck-fixture"/></head>'
                f"<docTitle><text>{title or ''}</text></docTitle>"
                f"<navMap>{navpoints}</navMap></ncx>",
            )
        for name, _, markup in documents:
            archive.writestr(name, markup)
        if images:
            archive.writestr("pixel.png", PIXEL_PNG)

    return {
        "chapters": chapters if include_toc else 0,
        "documents": chapters,
        "images": 1 if images else 0,
        "headings": chapters,
    }
