from pdffiller.pdf_fill import Placement, fill_acroform, fill_flat
from pdffiller.pdf_inspect import inspect_pdf
from pdffiller.pdf_render import page_count, render_page_png


def test_inspect_fillable_form(fillable_form):
    info = inspect_pdf(fillable_form)
    assert info.has_fields
    names = {f.name for f in info.fields}
    assert names == {"first_name", "email"}


def test_fill_acroform(fillable_form, tmp_path):
    out = tmp_path / "filled.pdf"
    fill_acroform(
        fillable_form,
        {"first_name": "Jonathan", "email": "j@example.com"},
        out,
    )
    info = inspect_pdf(str(out))
    values = {f.name: f.value for f in info.fields}
    assert values["first_name"] == "Jonathan"
    assert values["email"] == "j@example.com"


def test_fill_flat_overlay(flat_form, tmp_path):
    out = tmp_path / "flat_filled.pdf"
    fill_flat(
        flat_form,
        [Placement(page=0, x=72, y=680, value="Jonathan", font_size=10)],
        out,
    )
    assert page_count(str(out)) == 1
    assert out.exists()


def test_render_page_png(flat_form):
    data = render_page_png(flat_form, page_index=0, scale=1.0)
    assert data.startswith(b"\x89PNG")


def test_render_max_dimension(flat_form):
    data = render_page_png(
        flat_form, page_index=0, scale=2.0, max_dimension=200
    )
    assert data.startswith(b"\x89PNG")


def test_fill_flat_marks(flat_form, tmp_path):
    out = tmp_path / "marks.pdf"
    for mark in ("x", "check", "circle", "strike"):
        target = tmp_path / f"mark_{mark}.pdf"
        fill_flat(
            flat_form,
            [
                Placement(
                    page=0,
                    x=70.0,
                    y=676.0,
                    value="",
                    mark=mark,
                    x0=70.0,
                    y0=676.0,
                    x1=370.0,
                    y1=698.0,
                )
            ],
            target,
        )
        assert page_count(str(target)) == 1
