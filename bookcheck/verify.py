"""Comparing a book before and after conversion.

``ebook-convert`` returning 0 means the process did not crash. It does not mean
the table of contents survived, the author's name came through, or chapter 12
is still there. Those are separate questions, and this module asks them.

Findings are graded by what the reader actually loses:

``critical``
    The book is materially damaged. Most of the text is gone, or the output has
    no readable text at all.
``warning``
    Something a reader will notice and be annoyed by: a lost table of contents,
    a missing author, a large drop in images.
``info``
    Expected consequences of the format change. PDF has no reflowable chapter
    structure, so losing the navigable TOC on the way in is a property of the
    format, not a defect in the conversion.

Fields the inspector could not read are skipped rather than compared, so a
format whose word count is not recoverable never produces a phantom finding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .inspect_book import BookProfile, inspect_book

# Some loss is normal. Reflowing a book changes how words tokenize, and page
# furniture adds a few. Only a real gap should register.
WORD_LOSS_WARNING = 0.10
WORD_LOSS_CRITICAL = 0.35
IMAGE_LOSS_WARNING = 0.20

#: Conversions where losing navigation is the format's fault, not the tool's.
NO_NATIVE_TOC = {"pdf"}


@dataclass
class Finding:
    """One difference between the source book and the converted one."""

    check: str
    severity: str
    message: str
    detail: str = ""

    def __str__(self) -> str:
        tail = f"  ({self.detail})" if self.detail else ""
        return f"[{self.severity}] {self.check}: {self.message}{tail}"


@dataclass
class FidelityReport:
    """The result of comparing one conversion."""

    source: BookProfile
    output: BookProfile
    findings: List[Finding] = field(default_factory=list)

    @property
    def critical(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == "critical"]

    @property
    def warnings(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def score(self) -> int:
        """Fidelity out of 100, penalized by severity."""
        penalty = 0
        for finding in self.findings:
            penalty += {"critical": 40, "warning": 12, "info": 0}.get(finding.severity, 0)
        return max(0, 100 - penalty)

    @property
    def ok(self) -> bool:
        """True when nothing a reader would notice went wrong."""
        return not self.critical and not self.warnings

    @property
    def word_retention(self) -> Optional[float]:
        if not self.source.words or "words" in self.output.unavailable:
            return None
        return self.output.words / self.source.words

    def to_dict(self) -> dict:
        return {
            "source": self.source.to_dict(),
            "output": self.output.to_dict(),
            "score": self.score,
            "ok": self.ok,
            "word_retention": (
                round(self.word_retention, 4) if self.word_retention is not None else None
            ),
            "findings": [
                {
                    "check": f.check,
                    "severity": f.severity,
                    "message": f.message,
                    "detail": f.detail,
                }
                for f in self.findings
            ],
        }


def _comparable(profile: BookProfile, field_name: str) -> bool:
    """Whether a field was actually readable, as opposed to zero."""
    return field_name not in profile.unavailable


def compare(source: BookProfile, output: BookProfile) -> FidelityReport:
    """Compare two profiles and report what the conversion cost."""
    findings: List[Finding] = []

    # --- text ---------------------------------------------------------------
    if _comparable(source, "words") and _comparable(output, "words") and source.words:
        retention = output.words / source.words
        lost = 1.0 - retention
        if output.words == 0:
            findings.append(
                Finding(
                    "text_lost", "critical",
                    "The converted file contains no extractable text",
                    f"source had {source.words} words",
                )
            )
        elif lost > WORD_LOSS_CRITICAL:
            findings.append(
                Finding(
                    "text_lost", "critical",
                    f"{lost:.0%} of the text is missing after conversion",
                    f"{source.words} words to {output.words}",
                )
            )
        elif lost > WORD_LOSS_WARNING:
            findings.append(
                Finding(
                    "text_lost", "warning",
                    f"{lost:.0%} of the text is missing after conversion",
                    f"{source.words} words to {output.words}",
                )
            )
        elif retention > 1.5:
            # Far more text than the source usually means page furniture,
            # repeated headers, or the TOC printed into the body.
            findings.append(
                Finding(
                    "text_added", "info",
                    f"Output has {retention:.1f}x the source word count",
                    "likely page headers, footers, or an inlined TOC",
                )
            )

    # --- structure ----------------------------------------------------------
    if _comparable(source, "chapters") and _comparable(output, "chapters"):
        # A declared TOC vanishing is the loss, whether or not headings remain
        # to infer a chapter count from. Comparing counts alone misses it
        # entirely, because the inferred count usually matches.
        if source.has_toc and not output.has_toc:
            expected = output.format in NO_NATIVE_TOC
            findings.append(
                Finding(
                    "toc_lost",
                    "info" if expected else "warning",
                    (
                        f"No navigable table of contents in the {output.format.upper()}, "
                        "which is normal for the format"
                        if expected
                        else "The table of contents did not survive conversion"
                    ),
                    f"source declared {source.chapters} entries",
                )
            )
        elif source.chapters and output.chapters < source.chapters * 0.5:
            findings.append(
                Finding(
                    "toc_reduced", "warning",
                    "Most of the table of contents was lost",
                    f"{source.chapters} entries to {output.chapters}",
                )
            )

    # --- metadata -----------------------------------------------------------
    if _comparable(output, "metadata"):
        if source.title and not output.title:
            findings.append(
                Finding("title_lost", "warning", "The title did not survive conversion",
                        f"source title: {source.title!r}")
            )
        if source.author and not output.author:
            findings.append(
                Finding("author_lost", "warning", "The author did not survive conversion",
                        f"source author: {source.author!r}")
            )

    # --- images -------------------------------------------------------------
    if _comparable(source, "images") and _comparable(output, "images") and source.images:
        if output.images == 0:
            findings.append(
                Finding("images_lost", "warning", "All images are missing from the output",
                        f"source had {source.images}")
            )
        elif output.images < source.images * (1 - IMAGE_LOSS_WARNING):
            findings.append(
                Finding(
                    "images_reduced", "warning",
                    f"{source.images - output.images} of {source.images} images are missing",
                )
            )

    # --- the file itself ----------------------------------------------------
    if output.size_bytes == 0:
        findings.append(Finding("empty_output", "critical", "The converted file is empty"))

    order = {"critical": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: order.get(f.severity, 9))
    return FidelityReport(source=source, output=output, findings=findings)


def verify(source_path: str | Path, output_path: str | Path) -> FidelityReport:
    """Inspect both files and compare them."""
    return compare(inspect_book(source_path), inspect_book(output_path))


def format_report(report: FidelityReport, verbose: bool = False) -> str:
    """Render a fidelity report for the terminal."""
    source, output = report.source, report.output
    lines = [
        f"{Path(source.path).name}  ->  {Path(output.path).name}",
        f"Fidelity score: {report.score}/100" + ("" if report.ok else "  (issues found)"),
        "",
        f"{'':12} {'source':>12} {'output':>12}",
    ]

    def row(label: str, key: str) -> None:
        left = getattr(source, key)
        right = getattr(output, key)
        left_text = "n/a" if not _comparable(source, key) else str(left)
        right_text = "n/a" if not _comparable(output, key) else str(right)
        lines.append(f"{label:12} {left_text:>12} {right_text:>12}")

    row("words", "words")
    row("chapters", "chapters")
    row("images", "images")
    lines.append(f"{'title':12} {str(source.title or '-')[:12]:>12} {str(output.title or '-')[:12]:>12}")
    lines.append(f"{'author':12} {str(source.author or '-')[:12]:>12} {str(output.author or '-')[:12]:>12}")

    if report.findings:
        lines.append("")
        lines.append("Findings:")
        lines.extend(f"  {finding}" for finding in report.findings)
    else:
        lines.append("")
        lines.append("Nothing was lost that this can measure.")

    if verbose:
        for profile in (source, output):
            for note in profile.notes:
                lines.append(f"  note ({profile.format}): {note}")

    return "\n".join(lines)
