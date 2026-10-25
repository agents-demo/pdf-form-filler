"""Fill PDFs: AcroForm field filling and flat-PDF text overlay."""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pypdf import PdfReader, PdfWriter

_DEFAULT_FONT_SIZE = 10.0


@dataclass
class Placement:
    """A piece of text or a mark to place on a PDF page.

    Text mode (``mark == ""``): ``value`` is drawn with its baseline at
    ``(x, y)`` in PDF points (bottom-left origin).

    Mark modes: a symbol is drawn inside the rectangle ``(x0, y0, x1, y1)``:
    - ``"x"``: an X cross (checking a checkbox)
    - ``"check"``: a checkmark
    - ``"circle"``: an ellipse circling the box
    - ``"strike"``: a horizontal line striking through the box
    """

    page: int
    x: float
    y: float
    value: str = ""
    font_size: float = _DEFAULT_FONT_SIZE
    mark: str = ""
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0


def fill_acroform(
    path: str | Path,
    mapping: dict[str, str],
    output: str | Path,
) -> str:
    """Fill an AcroForm PDF with ``mapping`` (field name -> value).

    Returns the output path.
    """
    reader = PdfReader(str(path))
    writer = PdfWriter(clone_from=reader)
    writer.update_page_form_field_values(None, mapping, auto_regenerate=True)
    with open(str(output), "wb") as fh:
        writer.write(fh)
    return str(output)


def _draw_mark(c, mark: str, x0: float, y0: float, x1: float, y1: float) -> None:
    """Draw a mark symbol inside the given rectangle (PDF points)."""
    pad_x = (x1 - x0) * 0.22
    pad_y = (y1 - y0) * 0.22
    left, right = x0 + pad_x, x1 - pad_x
    bottom, top = y0 + pad_y, y1 - pad_y
    mid_y = (y0 + y1) / 2.0
    mid_x = (x0 + x1) / 2.0

    if mark == "x":
        c.setLineWidth(1.4)
        c.line(left, bottom, right, top)
        c.line(left, top, right, bottom)
    elif mark == "check":
        c.setLineWidth(1.4)
        p = c.beginPath()
        p.moveTo(left, mid_y)
        p.lineTo(mid_x, top)
        p.lineTo(right, bottom)
        c.drawPath(p, stroke=1, fill=0)
    elif mark == "circle":
        c.setLineWidth(1.2)
        c.ellipse(x0 + 1.5, y0 + 1.5, x1 - 1.5, y1 - 1.5, stroke=1, fill=0)
    elif mark == "strike":
        c.setLineWidth(1.2)
        c.line(x0, mid_y, x1, mid_y)


def _make_overlay(
    width: float,
    height: float,
    placements: list[Placement],
) -> io.BytesIO:
    """Build a single-page PDF overlay with the given text/mark placements."""
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(width, height))
    for p in placements:
        if p.mark:
            _draw_mark(c, p.mark, p.x0, p.y0, p.x1, p.y1)
        else:
            # y is the baseline position in PDF coordinates (bottom-left origin).
            c.setFont("Helvetica", p.font_size or _DEFAULT_FONT_SIZE)
            c.drawString(p.x, p.y, p.value)
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer


def fill_flat(
    path: str | Path,
    placements: list[Placement],
    output: str | Path,
) -> str:
    """Overlay ``placements`` onto a flat PDF and write ``output``.

    Returns the output path.
    """
    reader = PdfReader(str(path))
    writer = PdfWriter(clone_from=reader)

    # Group placements by page.
    by_page: dict[int, list[Placement]] = {}
    for p in placements:
        by_page.setdefault(p.page, []).append(p)

    for index, page in enumerate(writer.pages):
        page_placements = by_page.get(index)
        if page_placements:
            box = page.mediabox
            overlay_buf = _make_overlay(
                float(box.width), float(box.height), page_placements
            )
            overlay_pdf = PdfReader(overlay_buf)
            page.merge_page(overlay_pdf.pages[0])

    with open(str(output), "wb") as fh:
        writer.write(fh)
    return str(output)


def fill_pdf(
    path: str | Path,
    mapping: Optional[dict[str, str]] = None,
    placements: Optional[list[Placement]] = None,
    output: Optional[str | Path] = None,
) -> str:
    """Convenience dispatcher: fill AcroForm fields and/or overlay text."""
    src = Path(path)
    out = Path(output) if output else src.with_name(src.stem + "_filled.pdf")
    mapping = mapping or {}
    placements = placements or []

    if mapping:
        fill_acroform(path, mapping, out)
    if placements:
        # If we just wrote AcroForm output, overlay onto that result.
        fill_flat(out if mapping else src, placements, out)
    return str(out)
