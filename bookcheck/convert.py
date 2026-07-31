"""Converting a book and checking the result in one step.

The existing converter reports success when ``ebook-convert`` exits 0. This
wraps that call and then asks the separate question the exit code cannot
answer: did the book survive? A conversion that succeeds and quietly drops the
table of contents is reported as a success with findings attached, not as a
failure, because the file is still usable and the user should decide.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from .verify import FidelityReport, verify

DEFAULT_TIMEOUT = 300

CALIBRE_PATHS = (
    "/Applications/calibre.app/Contents/MacOS/ebook-convert",
    "/usr/bin/ebook-convert",
    "/usr/local/bin/ebook-convert",
    "/opt/homebrew/bin/ebook-convert",
)


def find_ebook_convert() -> Optional[str]:
    """Locate ``ebook-convert``, preferring whatever is on PATH."""
    found = shutil.which("ebook-convert")
    if found:
        return found
    for candidate in CALIBRE_PATHS:
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


@dataclass
class ConversionResult:
    """The outcome of one conversion, including whether the book survived."""

    source: Path
    output: Optional[Path]
    ok: bool
    error: str = ""
    report: Optional[FidelityReport] = None
    duration_seconds: float = 0.0

    @property
    def fidelity_score(self) -> Optional[int]:
        return self.report.score if self.report else None

    @property
    def needs_attention(self) -> bool:
        """True when the file converted but lost something a reader notices."""
        return bool(self.report and not self.report.ok)

    def to_dict(self) -> dict:
        return {
            "source": str(self.source),
            "output": str(self.output) if self.output else None,
            "ok": self.ok,
            "error": self.error,
            "duration_seconds": round(self.duration_seconds, 2),
            "fidelity": self.report.to_dict() if self.report else None,
        }


def convert(
    source: str | Path,
    output: str | Path,
    *,
    ebook_convert: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    check_fidelity: bool = True,
    extra_args: Sequence[str] = (),
) -> ConversionResult:
    """Convert one book and, unless told otherwise, verify the result."""
    import time

    source_path, output_path = Path(source), Path(output)
    binary = ebook_convert or find_ebook_convert()
    if not binary:
        return ConversionResult(
            source_path, None, False,
            "ebook-convert not found. Install Calibre and put it on your PATH.",
        )
    if not source_path.exists():
        return ConversionResult(source_path, None, False, f"{source_path} does not exist")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        process = subprocess.run(
            [binary, str(source_path), str(output_path), *extra_args],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ConversionResult(
            source_path, None, False,
            f"Conversion timed out after {timeout}s",
            duration_seconds=time.monotonic() - started,
        )
    except OSError as exc:
        # An explicitly supplied path that does not exist, or is not
        # executable. Same class of user error as Calibre not being installed,
        # so it gets the same kind of message instead of a traceback.
        return ConversionResult(
            source_path, None, False,
            f"Could not run {binary}: {exc.strerror or exc}",
            duration_seconds=time.monotonic() - started,
        )
    duration = time.monotonic() - started

    if process.returncode != 0:
        # Calibre's real explanation is usually the last line of stderr.
        stderr = process.stderr.decode("utf-8", errors="replace").strip()
        tail = stderr.splitlines()[-1] if stderr else f"exit code {process.returncode}"
        return ConversionResult(source_path, None, False, tail, duration_seconds=duration)

    if not output_path.exists() or output_path.stat().st_size == 0:
        return ConversionResult(
            source_path, output_path, False,
            "ebook-convert reported success but produced no usable file",
            duration_seconds=duration,
        )

    report = None
    if check_fidelity:
        try:
            report = verify(source_path, output_path)
        except Exception as exc:  # noqa: BLE001 - a failed check is not a failed conversion
            return ConversionResult(
                source_path, output_path, True,
                f"converted, but fidelity could not be checked: {exc}",
                duration_seconds=duration,
            )

    return ConversionResult(
        source_path, output_path, True, "", report=report, duration_seconds=duration
    )


def convert_many(
    sources: Sequence[str | Path],
    output_dir: str | Path,
    target_format: str,
    **kwargs,
) -> List[ConversionResult]:
    """Convert a batch, so a whole library can be checked in one pass."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    suffix = target_format if target_format.startswith(".") else f".{target_format}"

    results = []
    for source in sources:
        source_path = Path(source)
        results.append(convert(source_path, directory / f"{source_path.stem}{suffix}", **kwargs))
    return results
