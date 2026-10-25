from pdffiller.agent import (
    FillPlan,
    _apply_layout_boxes,
    _box_to_pdf,
    _complete_with_fallback,
    _parse_plan,
    _vision_scale,
)
from pdffiller.pdf_layout import Layout, RectBox, TextSpan
from pdffiller.llm import LLMError, extract_json
from pdffiller.pdf_inspect import PdfFormInfo

import pytest


def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_embedded():
    assert extract_json('Here you go:\n{"a": 1}\nthanks') == {"a": 1}


def test_extract_json_invalid():
    with pytest.raises(LLMError):
        extract_json("no json here")


def test_parse_plan():
    raw = {
        "fill": [
            {"name": "first_name", "value": "Jonathan", "page": 0, "x": 10, "y": 20}
        ],
        "missing": [
            {
                "name": "email",
                "question": "Email?",
                "category": "personal",
                "key": "Email",
                "page": None,
                "x": None,
                "y": None,
            }
        ],
    }
    plan = _parse_plan(raw, used_vision=True)
    assert len(plan.fill) == 1
    assert plan.fill[0].x == 10.0
    assert len(plan.missing) == 1
    assert plan.missing[0].category == "personal"


def test_box_to_pdf_conversion():
    # Page height 792pt, scale 2 px/pt. Box in image px: x=200, y=100, w=600, h=40
    # -> top_pdf = 792 - 140/2 = 722, bottom_pdf = 792 - 100/2 = 742
    # (image y grows downward, so y=100 is the TOP edge).
    x, y, page, font, box = _box_to_pdf(
        200, 100, 600, 40, 0, scale=2.0, page_heights=[792.0]
    )
    assert page == 0
    assert x == pytest.approx(102.0)  # 200/2 + 2pt padding
    # center of 722..742 is 732; baseline = center - font*0.35
    expected_center = 732.0
    assert y == pytest.approx(expected_center - font * 0.35)
    assert 6.0 <= font <= 11.0
    # box rect in PDF coords: x0=100, y0=742, x1=100+300, y1=722
    assert box is not None
    assert box[0] == pytest.approx(100.0)
    assert box[1] == pytest.approx(742.0)
    assert box[2] == pytest.approx(400.0)
    assert box[3] == pytest.approx(722.0)


def test_box_to_pdf_bare_point():
    x, y, page, font, box = _box_to_pdf(
        200, 100, None, None, 0, scale=2.0, page_heights=[792.0]
    )
    assert page == 0
    assert x == pytest.approx(102.0)
    assert y == pytest.approx(792.0 - 50.0 - font)
    assert box is None


def test_vision_scale_caps_width():
    info = PdfFormInfo(path="x", pages=1, page_sizes=[(612.0, 792.0)])
    assert _vision_scale(info, max_width=3000.0) == pytest.approx(3.0)  # clamped
    assert _vision_scale(info, max_width=1100.0) == pytest.approx(1100.0 / 612.0)


def _layout_with_label_and_box():
    layout = Layout()
    layout.spans.append(
        TextSpan(text="First name", page=0, x0=72.0, y0=722.0, x1=110.0, y1=730.0)
    )
    layout.boxes.append(RectBox(page=0, x0=70.0, y0=700.0, x1=370.0, y1=718.0))
    return layout


def test_apply_layout_boxes_places_deterministically():
    from pdffiller.agent import FillEntry, MissingEntry

    plan = FillPlan(
        fill=[FillEntry(name="First name", value="Jonathan", page=0, x=999.0, y=999.0)],
        missing=[MissingEntry(name="Email", question="Email?", page=0)],
    )
    placed = _apply_layout_boxes(plan, _layout_with_label_and_box())
    assert placed == 1
    entry = plan.fill[0]
    # Box: x0=70, y=700..718 -> text starts at x=72 and is vertically centered.
    assert entry.x == pytest.approx(72.0)
    assert 705.0 <= entry.y <= 712.0
    assert entry.font_size is not None
    # Email has no label in the layout -> untouched model coordinates.
    assert plan.missing[0].x == 999.0 or plan.missing[0].x is None


def test_apply_layout_boxes_skips_when_no_label():
    from pdffiller.agent import FillEntry

    plan = FillPlan(fill=[FillEntry(name="Unknown", value="x", page=0, x=5.0, y=6.0)])
    placed = _apply_layout_boxes(plan, _layout_with_label_and_box())
    assert placed == 0
    assert plan.fill[0].x == 5.0


class _FakeService:
    calls: list[bool] = []
    failures_left = 0

    def __init__(self, config=None):
        from pdffiller.config import LLMConfig

        self.config = config if config is not None else LLMConfig(api_key="x", verify_ssl=True)

    async def complete(self, system, user, images=None):
        type(self).calls.append(bool(self.config.verify_ssl))
        if type(self).failures_left > 0:
            type(self).failures_left -= 1
            raise RuntimeError("APIConnectionError: Connection error")
        return '{"fill": [], "missing": []}'


async def test_complete_with_fallback_recovers_on_retry(monkeypatch):
    monkeypatch.setattr("pdffiller.agent._RETRY_DELAYS", (0.0, 0.0))
    _FakeService.calls = []
    _FakeService.failures_left = 1
    service = _FakeService()
    out = await _complete_with_fallback(service, "s", "u", [])
    assert out == '{"fill": [], "missing": []}'
    assert _FakeService.calls == [True, True]


async def test_complete_with_fallback_ssl_fallback(monkeypatch):
    monkeypatch.setattr("pdffiller.agent._RETRY_DELAYS", (0.0, 0.0))
    _FakeService.calls = []
    _FakeService.failures_left = 99
    service = _FakeService()
    monkeypatch.setattr("pdffiller.agent.LLMService", _FakeService)
    with pytest.raises(RuntimeError):
        await _complete_with_fallback(service, "s", "u", [])
    # Three same-config retries, then one verify_ssl=False fallback attempt.
    assert _FakeService.calls == [True, True, True, False]


async def test_complete_with_fallback_no_retry_on_other_errors():
    _FakeService.calls = []
    _FakeService.failures_left = 99
    service = _FakeService()

    async def bad_complete(self, system, user, images=None):
        type(self).calls.append(bool(self.config.verify_ssl))
        raise ValueError("AuthenticationError: bad key")

    service.complete = bad_complete.__get__(service)
    with pytest.raises(ValueError):
        await _complete_with_fallback(service, "s", "u", [])
    assert _FakeService.calls == [True]  # no retries for non-connection errors
