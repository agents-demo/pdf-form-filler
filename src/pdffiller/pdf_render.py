"""Render PDF pages to PNG bytes for the GUI preview and for LLM vision."""
from __future__ import annotations

import io
from pathlib import Path

import pypdfium2 as pdfium


def page_count(path: str | Path) -> int:
    """Return the number of pages in a PDF."""
    pdf = pdfium.PdfDocument(str(path))
    try:
        return len(pdf)
    finally:
        pdf.close()


def render_page_png(
    path: str | Path,
    page_index: int = 0,
    scale: float = 2.0,
    max_dimension: int | None = None,
) -> bytes:
    """Render a single page to a PNG byte string.

    Args:
        path: PDF file path.
        page_index: Zero-based page index.
        scale: Render scale in pixels per PDF point.
        max_dimension: Optional cap on the larger image dimension (pixels);
            the image is down-scaled afterwards if needed.

    Returns:
        PNG-encoded image bytes.
    """
    return _render_page(path, page_index, scale, max_dimension, fmt="PNG")


def render_page_jpeg(
    path: str | Path,
    page_index: int = 0,
    scale: float = 2.0,
    max_dimension: int | None = None,
    quality: int = 80,
) -> bytes:
    """Render a single page to a JPEG byte string (much smaller payloads).

    Use this for sending page images to a vision-capable LLM.
    """
    return _render_page(
        path, page_index, scale, max_dimension, fmt="JPEG", quality=quality
    )


def _render_page(
    path: str | Path,
    page_index: int,
    scale: float,
    max_dimension: int | None,
    fmt: str,
    quality: int = 80,
) -> bytes:
    pdf = pdfium.PdfDocument(str(path))
    try:
        page = pdf[page_index]
        bitmap = page.render(scale=scale)
        pil = bitmap.to_pil()
        if max_dimension and max(pil.size) > max_dimension:
            ratio = max_dimension / max(pil.size)
            pil = pil.resize(
                (int(pil.width * ratio), int(pil.height * ratio))
            )
        if pil.mode != "RGB":
            pil = pil.convert("RGB")
        buffer = io.BytesIO()
        pil.save(buffer, format=fmt, quality=quality)
        return buffer.getvalue()
    finally:
        pdf.close()


def render_pages_png(
    path: str | Path,
    scale: float = 2.0,
    max_dimension: int | None = None,
) -> list[bytes]:
    """Render every page of ``path`` to a list of PNG byte strings."""
    pdf = pdfium.PdfDocument(str(path))
    try:
        images = []
        for i in range(len(pdf)):
            bitmap = pdf[i].render(scale=scale)
            pil = bitmap.to_pil()
            if max_dimension and max(pil.size) > max_dimension:
                ratio = max_dimension / max(pil.size)
                pil = pil.resize(
                    (int(pil.width * ratio), int(pil.height * ratio))
                )
            buffer = io.BytesIO()
            pil.save(buffer, format="PNG")
            images.append(buffer.getvalue())
        return images
    finally:
        pdf.close()
