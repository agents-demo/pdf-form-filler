"""Inspect PDF forms: extract AcroForm fields, page text and page geometry."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pypdf import PdfReader

# PDF field type abbreviations -> human friendly names
_FT_NAMES = {
    "/Tx": "text",
    "/Btn": "checkbox",
    "/Ch": "choice",
    "/Sig": "signature",
}


@dataclass
class FieldInfo:
    name: str
    type: str = "text"
    value: str = ""

    @property
    def is_checkbox(self) -> bool:
        return self.type == "checkbox"


@dataclass
class PdfFormInfo:
    path: str
    pages: int = 0
    page_sizes: list[tuple[float, float]] = field(default_factory=list)
    fields: list[FieldInfo] = field(default_factory=list)
    page_text: list[str] = field(default_factory=list)
    is_form: bool = False

    @property
    def has_fields(self) -> bool:
        return bool(self.fields)


def _field_type(raw: object) -> str:
    value = str(raw).strip() if raw else ""
    return _FT_NAMES.get(value, value.lstrip("/") or "text")


def inspect_pdf(path: str | Path) -> PdfFormInfo:
    """Open ``path`` and return structured information about its form."""
    reader = PdfReader(str(path))
    info = PdfFormInfo(path=str(path))

    info.pages = len(reader.pages)
    info.page_sizes = []
    for page in reader.pages:
        box = page.mediabox
        info.page_sizes.append((float(box.width), float(box.height)))

    # AcroForm fields
    raw_fields = reader.get_fields() or {}
    for name, field in raw_fields.items():
        ft = field.get("/FT")
        value = field.get("/V")
        if isinstance(value, (list, tuple)):
            # checkbox "on" state etc.
            value = value[0] if value else ""
        info.fields.append(
            FieldInfo(
                name=str(name),
                type=_field_type(ft),
                value="" if value is None else str(value),
            )
        )
    info.is_form = bool(info.fields)

    # Page text (useful for flat PDFs without form fields)
    for page in reader.pages:
        try:
            info.page_text.append(page.extract_text() or "")
        except Exception:  # pragma: no cover - malformed PDFs
            info.page_text.append("")

    return info
