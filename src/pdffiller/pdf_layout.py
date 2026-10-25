"""Extract exact text and rectangle positions from a PDF.

Used to place filled values deterministically: the vision model is good at
*identifying* fields but drifts when estimating absolute pixel coordinates,
so whenever the PDF itself contains extractable label text and drawn boxes we
derive positions from the PDF instead of trusting the model's coordinates.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium


@dataclass
class TextSpan:
    """One line of text on a page, with its exact bbox (PDF points, y-up)."""

    text: str
    page: int
    x0: float
    y0: float  # bottom
    x1: float
    y1: float  # top
    # Per-character boxes, parallel to ``text``'s characters.
    chars: list[tuple[float, float, float, float]] = field(default_factory=list)

    def subspan(self, needle: str) -> tuple[float, float, float, float] | None:
        """Bbox of ``needle`` inside this line (case-insensitive)."""
        idx = self.text.lower().find(needle.lower())
        if idx < 0 or not self.chars:
            return None
        end = idx + len(needle)
        boxes = self.chars[idx:end]
        return (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )


@dataclass
class RectBox:
    page: int
    x0: float
    y0: float  # bottom
    x1: float
    y1: float  # top


@dataclass
class Layout:
    spans: list[TextSpan] = field(default_factory=list)
    boxes: list[RectBox] = field(default_factory=list)

    def find_label(self, page: int, label: str) -> tuple[float, float, float, float] | None:
        """Locate a label's exact bbox on a page; None if not found."""
        normalized = re.sub(r"\s+", " ", (label or "").lower().strip())
        if not normalized:
            return None
        for span in self.spans:
            if span.page != page:
                continue
            line = re.sub(r"\s+", " ", span.text.lower().strip())
            if line == normalized:
                return (span.x0, span.y0, span.x1, span.y1)
            if line.startswith(normalized) or line.endswith(normalized):
                return span.subspan(normalized) or (span.x0, span.y0, span.x1, span.y1)
            if normalized in line and len(normalized) >= 4:
                sub = span.subspan(normalized)
                if sub is not None:
                    return sub
        return None


def _group_lines(chars: list[tuple[float, float, float, float, str]]) -> list[list]:
    """Cluster characters into lines (y-proximity), sorted left-to-right."""
    by_y = sorted(chars, key=lambda c: -c[1])
    lines: list[list] = []
    current: list = []
    last_y: float | None = None
    for ch in by_y:
        if last_y is not None and abs(ch[1] - last_y) > 3.0:
            lines.append(current)
            current = []
        current.append(ch)
        last_y = ch[1]
    if current:
        lines.append(current)
    return [sorted(line, key=lambda c: c[0]) for line in lines]


def extract_layout(path: str | Path) -> Layout:
    """Extract text lines and drawn rectangles from every page."""
    layout = Layout()
    pdf = pdfium.PdfDocument(str(path))
    try:
        for page_index in range(len(pdf)):
            page = pdf[page_index]

            # Text: character-level extraction, grouped into lines.
            textpage = page.get_textpage()
            chars: list[tuple[float, float, float, float, str]] = []
            for i in range(textpage.count_chars()):
                box = textpage.get_charbox(i)  # (left, bottom, right, top), y-up
                ch = textpage.get_text_range(i, 1)
                if not ch:
                    continue
                if ch in "\r\n":
                    ch = " "  # keep word spacing; drop line breaks
                chars.append((box[0], box[1], box[2], box[3], ch))
            for line in _group_lines(chars):
                text = "".join(c[4] for c in line)
                layout.spans.append(
                    TextSpan(
                        text=text,
                        page=page_index,
                        x0=min(c[0] for c in line),
                        y0=min(c[1] for c in line),
                        x1=max(c[2] for c in line),
                        y1=max(c[3] for c in line),
                        chars=[(c[0], c[1], c[2], c[3]) for c in line],
                    )
                )

            # Drawn rectangles (form boxes).
            for obj in page.get_objects(
                filter=[pdfium.raw.FPDF_PAGEOBJ_PATH], max_depth=0
            ):
                x0, y0, x1, y1 = obj.get_bounds()
                width, height = x1 - x0, y1 - y0
                if 4.0 <= width <= 1200.0 and 3.0 <= height <= 300.0:
                    layout.boxes.append(RectBox(page_index, x0, y0, x1, y1))
    finally:
        pdf.close()
    return layout
