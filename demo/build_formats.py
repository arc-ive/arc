#!/usr/bin/env python3
"""Render demo knowledge documents into PDF and DOCX (issue #299).

The Markdown files are the single source of truth. These renderings are
generated from them so the FACTS cannot drift: if a leave allowance
changes in the Markdown, regenerating keeps every format agreeing, and
EXPECTED_ANSWERS.md stays valid for all of them.

The point is to exercise ingestion with formats a customer actually
sends, and to prove a known fact survives a round trip through a real
parser -- not only through a text file Arc never had to parse.

    python demo/build_formats.py
"""

from __future__ import annotations

import re
import sys
import textwrap
from pathlib import Path

PACK = Path(__file__).parent / "knowledge"

# One per format, chosen because each exercises something different: a
# table-heavy policy for DOCX, flowing prose for PDF.
AS_DOCX = ["leave-policy.md", "product-catalogue.md"]
AS_PDF = ["it-security-policy.md", "benefits.md"]


def _plain(markdown: str) -> list[str]:
    """Flatten Markdown to document lines, unwrapping prose paragraphs.

    Hard-wrapping is a Markdown source convention, not a document one. A
    real PDF or Word file does not break a sentence mid-phrase, and
    keeping the breaks splits facts across paragraphs: "8 weeks at full /
    pay" then reads as two fragments, which is both wrong as a rendering
    and worse for chunking. Consecutive prose lines are therefore joined
    into one paragraph.

    Headings, blank lines and table rows stay on their own lines, because
    each is a real boundary rather than an artefact of wrapping.
    """
    out: list[str] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            out.append(" ".join(paragraph))
            paragraph.clear()

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if re.fullmatch(r"\s*\|[\s\-:|]+\|\s*", line):
            continue  # table separator row

        is_heading = bool(re.match(r"^#+\s", line))
        is_table = line.strip().startswith("|")
        is_bullet = bool(re.match(r"^\s*[-*]\s", line))

        line = re.sub(r"^#+\s*", "", line)
        line = line.replace("**", "").replace("`", "")

        if is_table:
            flush()
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            out.append(" | ".join(cells))
        elif not line.strip():
            flush()
            out.append("")
        elif is_heading or is_bullet:
            flush()
            out.append(line)
        else:
            paragraph.append(line.strip())

    flush()
    return out


def _write_docx(source: Path, target: Path) -> None:
    import docx

    document = docx.Document()
    for line in _plain(source.read_text(encoding="utf-8")):
        document.add_paragraph(line)
    document.save(target)


def _write_pdf(source: Path, target: Path) -> None:
    """Emit a PDF with a real text layer, without a rendering library.

    Arc extracts text, so the text layer is the only thing that matters.
    Pulling in a full PDF toolkit to produce a fixture would be a
    dependency the deployment then has to justify.
    """
    # Wrap, never truncate. Unwrapped paragraphs are long, and cutting
    # them at a fixed width silently drops the end of a sentence -- which
    # is exactly how a known fact disappears from a fixture that still
    # looks fine.
    wrapped: list[str] = []
    for line in _plain(source.read_text(encoding="utf-8")):
        if not line.strip():
            continue
        wrapped.extend(textwrap.wrap(line, width=105) or [line])
    lines = wrapped

    def escape(value: str) -> str:
        return value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    pages, current = [], []
    for line in lines:
        current.append(line)
        if len(current) >= 46:
            pages.append(current)
            current = []
    if current:
        pages.append(current)

    objects: list[bytes] = []
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    font_obj = 3 + len(pages) * 2
    for index, page_lines in enumerate(pages):
        body = ["BT /F1 10 Tf 54 750 Td 13 TL"]
        for line in page_lines:
            body.append(f"({escape(line)}) Tj T*")
        body.append("ET")
        stream = "\n".join(body).encode("latin-1", "replace")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_obj} 0 R >> >> "
            f"/Contents {4 + index * 2} 0 R >>".encode()
        )
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF"
    ).encode()
    target.write_bytes(bytes(out))


def main() -> int:
    built = []
    for name in AS_DOCX:
        target = (PACK / name).with_suffix(".docx")
        _write_docx(PACK / name, target)
        built.append(target.name)
    for name in AS_PDF:
        target = (PACK / name).with_suffix(".pdf")
        _write_pdf(PACK / name, target)
        built.append(target.name)

    print(f"Built {len(built)} files from Markdown:")
    for name in built:
        print(f"  {name}")
    print("\nThe Markdown remains the source of truth. Regenerate after editing it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
