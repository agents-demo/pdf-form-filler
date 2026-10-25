"""Generate sample PDF forms for testing.

Creates:
- sample/sample_form.pdf      (fillable AcroForm: text fields + checkboxes)
- sample/sample_flat.pdf      (flat PDF: text boxes, checkboxes, circle and
                               strikethrough sections, no form fields)
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

HERE = Path(__file__).resolve().parent
SAMPLE_DIR = HERE.parent / "sample"

# (field name used in the form, human label drawn on the page)
FIELDS = [
    ("first_name", "First name"),
    ("last_name", "Last name"),
    ("phone", "Phone"),
    ("id", "ID / passport number"),
    ("email", "Email"),
    ("address", "Address"),
    ("city", "City"),
    ("zip", "Zip code"),
    ("birth_date", "Date of birth"),
]

CHECKBOX_LABELS = ["Single", "Married", "Divorced"]
CIRCLE_LABELS = ["Male", "Female"]
STRIKE_LABELS = ["Yes", "No"]


def _layout():
    start_y = 700
    step = 40
    return [(name, label, 72, start_y - i * step) for i, (name, label) in enumerate(FIELDS)]


def _draw_text_fields(c, with_form_fields: bool) -> None:
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, 760, "Personal Information Form")
    c.setFont("Helvetica", 11)
    for name, label, x, y in _layout():
        c.drawString(x, y + 22, label)
        if with_form_fields:
            c.acroForm.textfield(
                name=name, tooltip=label, x=x, y=y, width=300, height=18
            )
        else:
            c.rect(x - 2, y - 2, 300, 22, stroke=1, fill=0)


def _draw_mark_sections(c, with_form_fields: bool) -> None:
    x = 72

    # --- tick (checkbox) section ---------------------------------------
    y = 320
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x, y + 44, "Tick (mark X) where applicable:")
    c.setFont("Helvetica", 11)
    for i, label in enumerate(CHECKBOX_LABELS):
        cx = x + i * 110
        c.drawString(cx, y + 22, label)
        if with_form_fields:
            c.acroForm.checkbox(
                name=label.lower(), tooltip=label, x=cx + 55, y=y, size=14
            )
        else:
            c.rect(cx + 55, y, 14, 14, stroke=1, fill=0)

    # --- circle section (plain words; the app draws the circle mark) -----
    cy = y - 70
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x, cy + 44, "Circle the correct answer:")
    c.setFont("Helvetica", 11)
    for i, label in enumerate(CIRCLE_LABELS):
        cx = x + i * 110
        c.drawString(cx, cy + 22, label)

    # --- strikethrough section (plain words; the app draws the strike) ---
    sy = cy - 70
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x, sy + 44, "Cross out (strike through) what is not applicable:")
    c.setFont("Helvetica", 11)
    for i, label in enumerate(STRIKE_LABELS):
        cx = x + i * 110
        c.drawString(cx, sy + 22, label)


def make_fillable_form(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=letter)
    _draw_text_fields(c, with_form_fields=True)
    _draw_mark_sections(c, with_form_fields=True)
    c.save()


def make_flat_form(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=letter)
    _draw_text_fields(c, with_form_fields=False)
    _draw_mark_sections(c, with_form_fields=False)
    c.save()


if __name__ == "__main__":
    make_fillable_form(SAMPLE_DIR / "sample_form.pdf")
    make_flat_form(SAMPLE_DIR / "sample_flat.pdf")
    print(f"Wrote sample forms to {SAMPLE_DIR}")
