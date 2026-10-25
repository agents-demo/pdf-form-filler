"""Shared pytest fixtures."""
from __future__ import annotations

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


@pytest.fixture
def fillable_form(tmp_path):
    """Create a small fillable AcroForm PDF and return its path."""
    path = tmp_path / "form.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    c.drawString(72, 720, "Test Form")
    c.acroForm.textfield(name="first_name", tooltip="First name", x=72, y=680, width=300, height=18)
    c.acroForm.textfield(name="email", tooltip="Email", x=72, y=640, width=300, height=18)
    c.save()
    return str(path)


@pytest.fixture
def flat_form(tmp_path):
    """Create a flat (non-form) PDF with drawn boxes and return its path."""
    path = tmp_path / "flat.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    c.drawString(72, 700, "First name")
    c.rect(70, 676, 300, 22, stroke=1, fill=0)
    c.save()
    return str(path)
