"""Extract plain text from a resume file and fingerprint it.

The extraction is deliberately deterministic and model-free: a language model
reading a PDF can hallucinate content or describe an image instead of reading
it, and it costs tokens on every run. Text extraction is a mechanical job, so it
belongs in a tool. The model is used later, once, to turn the extracted text
into structured profile data.

Usage:
    python3 tools/extract_resume.py resumes/<file> [...]
    python3 tools/extract_resume.py --all

Output (stdout) is a JSON object:

    {
      "slug": "<name>--<focus>--v<date>",
      "source": "resumes/<name>--<focus>--v<date>.pdf",
      "extracted": "resumes/extracted/<name>--<focus>--v<date>.txt",
      "sha256": "<hash of the source file>",
      "bytes": 50505,
      "chars": 3834,
      "lines": 51,
      "extractor": "pypdf",
      "extractor_version": "6.21.2",
      "warnings": []
    }

Exit codes:
    0 - every file extracted
    1 - one or more files could not be read or produced no text
    2 - bad usage
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paths import ROOT, extracted_dir, resumes_dir  # noqa: E402

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".text", ".md"}


def slug_for(path: Path) -> str:
    """Return the slug of a resume file.

    The naming convention is ``<owner>--<variant>--v<date>``, so the ``--``
    separator is preserved: each part is slugified on its own and the parts are
    rejoined with a double dash. A plain character-class replacement would
    collapse ``--`` into a single dash and lose the distinction.
    """
    parts = [part for part in path.stem.strip().lower().split("--") if part]
    slug = "--".join(re.sub(r"[^a-z0-9]+", "-", part).strip("-") for part in parts)
    return slug or "resume"


def sha256_of(path: Path) -> str:
    """Return the hex sha256 of a file's bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_pdf(path: Path) -> tuple[str, str, str, list[str]]:
    """Return (text, extractor, version, warnings) for a PDF."""
    warnings: list[str] = []
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError(
            "pypdf is not installed. Install it with: pip install pypdf"
        ) from None
    reader = PdfReader(str(path))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            pages.append(page.extract_text() or "")
        except Exception as exc:  # noqa: BLE001 - one bad page must not lose the rest
            warnings.append(f"page {index} failed to extract: {exc}")
    text = "\n".join(pages)
    try:
        version = str(__import__("pypdf").__version__)
    except Exception:  # noqa: BLE001
        version = "unknown"
    if not text.strip():
        warnings.append("no text layer found (the PDF may be a scan)")
    return text, "pypdf", version, warnings


def extract_docx(path: Path) -> tuple[str, str, str, list[str]]:
    """Return (text, extractor, version, warnings) for a .docx file.

    Uses only the standard library: a .docx is a zip archive of XML, and the
    document text lives in word/document.xml. This keeps the project
    installable without pulling in python-docx for one file format.
    """
    warnings: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if "word/document.xml" not in names:
                raise RuntimeError("not a Word document (word/document.xml missing)")
            xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise RuntimeError(f"unreadable .docx: {exc}") from None
    # Paragraph and line breaks become newlines, tabs stay tabs.
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    text = html.unescape(text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        warnings.append("document contains no text")
    return text, "stdlib-zipfile", "1", warnings


def extract_text(path: Path) -> tuple[str, str, str, list[str]]:
    """Return (text, extractor, version, warnings) for a plain-text file."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    return raw, "plaintext", "1", []


def extract(path: Path) -> dict:
    """Extract one resume and write its text cache. Returns a metadata dict."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text, extractor, version, warnings = extract_pdf(path)
    elif suffix == ".docx":
        text, extractor, version, warnings = extract_docx(path)
    elif suffix in {".txt", ".text", ".md"}:
        text, extractor, version, warnings = extract_text(path)
    else:
        raise RuntimeError(f"unsupported format '{suffix}' (use .pdf, .docx or .txt)")

    text = text.strip()
    if not text:
        raise RuntimeError("extraction produced no text")

    slug = slug_for(path)
    target = extracted_dir() / f"{slug}.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text + "\n", encoding="utf-8")

    try:
        relative_source = str(path.resolve().relative_to(ROOT))
    except ValueError:
        relative_source = str(path)
    try:
        relative_target = str(target.resolve().relative_to(ROOT))
    except ValueError:
        relative_target = str(target)

    return {
        "slug": slug,
        "source": relative_source,
        "extracted": relative_target,
        "sha256": sha256_of(path),
        "bytes": path.stat().st_size,
        "chars": len(text),
        "lines": len(text.splitlines()),
        "extractor": extractor,
        "extractor_version": version,
        "warnings": warnings,
    }


def discover() -> list[Path]:
    """Return every supported resume file in resumes/, sorted.

    README files are documentation, not resumes, and are skipped.
    """
    if not resumes_dir().is_dir():
        return []
    return sorted(
        path
        for path in resumes_dir().iterdir()
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_SUFFIXES
        and not path.name.lower().startswith("readme")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", type=Path, help="resume files to extract")
    parser.add_argument("--all", action="store_true", help="extract every resume in resumes/")
    parser.add_argument("--quiet", action="store_true", help="print only the summary")
    args = parser.parse_args()

    if args.all or not args.files:
        targets = discover()
        if not targets:
            print("no resume files found in resumes/", file=sys.stderr)
            return 1
    else:
        targets = []
        for candidate in args.files:
            path = candidate if candidate.is_absolute() else (ROOT / candidate)
            if not path.exists():
                print(f"not found: {candidate}", file=sys.stderr)
                return 1
            targets.append(path)

    results = []
    failed = False
    for path in targets:
        try:
            results.append(extract(path))
        except (RuntimeError, OSError) as exc:
            failed = True
            print(f"extract_resume: {path.name}: {exc}", file=sys.stderr)

    if args.quiet:
        print(json.dumps({"extracted": len(results), "failed": failed}, ensure_ascii=False))
    else:
        print(json.dumps({"resumes": results}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
