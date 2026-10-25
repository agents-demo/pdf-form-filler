"""Tests for PDF layout extraction and deterministic placement."""
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from pdffiller.pdf_layout import extract_layout


def _make_flat(path, labels, with_boxes=True):
    c = canvas.Canvas(str(path), pagesize=letter)
    for i, label in enumerate(labels):
        y = 700 - i * 40
        c.drawString(72, y + 22, label)
        if with_boxes:
            c.rect(70, y - 2, 300, 22, stroke=1, fill=0)
    c.save()


def test_extract_layout_finds_labels_and_boxes(tmp_path):
    path = tmp_path / "flat.pdf"
    labels = ["First name", "Last name", "Phone", "Email"]
    _make_flat(path, labels)
    layout = extract_layout(str(path))
    assert len(layout.boxes) == 4
    for label in labels:
        assert layout.find_label(0, label) is not None


def test_extract_layout_no_boxes_when_none_drawn(tmp_path):
    path = tmp_path / "flat.pdf"
    _make_flat(path, ["First name"], with_boxes=False)
    layout = extract_layout(str(path))
    assert layout.boxes == []
    assert layout.find_label(0, "First name") is not None


def test_find_label_returns_exact_label_bbox(tmp_path):
    path = tmp_path / "flat.pdf"
    _make_flat(path, ["First name"])
    layout = extract_layout(str(path))
    bbox = layout.find_label(0, "First name")
    assert bbox is not None
    x0, y0, x1, y1 = bbox
    # Label drawn with baseline at 722, so its bbox sits just above it.
    assert y1 > 722
    assert x0 < 100


def test_find_label_case_insensitive(tmp_path):
    path = tmp_path / "flat.pdf"
    _make_flat(path, ["Date of birth"])
    layout = extract_layout(str(path))
    assert layout.find_label(0, "DATE OF BIRTH") is not None
    assert layout.find_label(0, "nope") is None
