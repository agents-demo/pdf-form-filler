"""Interpret a PDF form and map the user's data onto it.

Uses the openJiuwen agent-core library:

* AcroForm PDFs (text-based) are interpreted by a :class:`ReActAgent` that is
  given ``read_pdf_fields`` and ``read_data`` tools.
* Flat/scanned PDFs are interpreted through openJiuwen's ``Model`` with the
  rendered page images attached (multimodal / vision).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .config import LLMConfig
from .llm import LLMService, extract_json
from .pdf_inspect import PdfFormInfo
from .pdf_layout import Layout, RectBox, extract_layout
from .pdf_render import render_page_jpeg

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a precise assistant that fills PDF forms using a user's personal data.

You are given:
1. A list of fields/labels in a PDF form.
2. The user's data (markdown with `# category` sections and `- key : value` items).

Rules:
- Match fields to data values semantically (case-insensitive; synonyms allowed,
  e.g. "Surname"/"Family name" match "Last name").
- Fill every field you can find a value for.
- For fields you CANNOT fill, add a "missing" entry with a clear question for
  the user plus your best guess for the "category" and "key" the answer belongs
  to in the data file (use "personal" if unsure).
- NEVER invent values. Use only values present in the data, or mark missing.
- For checkbox fields, use "X" to tick, "" to leave unticked.
- If a field is a choice group (checkbox/radio options), list the visible
  choices in "options".
- Report the field's designated mark from the form's instructions as "mark":
  "checkbox" when the form says to tick/check (☐, ☑), "circle" when it says
  to circle (◯), "strike" when it says to cross/strike out; otherwise "text".

Respond with ONLY a JSON object (no markdown fences, no commentary) of the form:
{"fill": [{"name": "<field>", "value": "<value>",
           "category": "<category|null>", "key": "<key|null>",
           "mark": "<text|checkbox|circle|strike>",
           "options": ["<choice>", "..."]}],
 "missing": [{"name": "<field>", "question": "<question>",
              "category": "<category|null>", "key": "<key|null>",
              "mark": "<text|checkbox|circle|strike>",
              "options": ["<choice>", "..."]}]}
"""

_SYSTEM_PROMPT_VISION = """\
You are a precise assistant that fills PDF forms using a user's personal data.

You are shown images of the pages of a PDF form plus the user's data (markdown
with `# category` sections and `- key : value` items).

Read the form from the images and map the user's data onto it.

Rules:
- Identify each fillable field from the images (the empty box/line to write
  into, NOT the label text next to it).
- For each field report the bounding rectangle of the box/field itself in image
  pixels (top-left origin) as "x", "y" (top-left corner), "width", "height",
  and the 0-based "page" number the field appears on.
- Match fields to data values semantically (case-insensitive; synonyms allowed,
  e.g. "Surname"/"Family name" match "Last name").
- Fill every field you can find a value for.
- For fields you CANNOT fill, add a "missing" entry with a clear question for
  the user plus your best guess for the "category" and "key" the answer belongs
  to in the data file (use "personal" if unsure).
- NEVER invent values. Use only values present in the data, or mark missing.
- If a field is a choice group (checkboxes/radio options), list each visible
  choice in "options" with its own box rectangle (top-left origin, image px).
- Report the field's designated mark from the form's instructions as "mark":
  "checkbox" when the form says to tick/check (☐, ☑), "circle" when it says
  to circle (◯), "strike" when it says to cross/strike out; otherwise "text".

Respond with ONLY a JSON object (no markdown fences, no commentary) of the form:
{"fill": [{"name": "<label>", "value": "<value>", "page": <int>,
           "box": {"x": <int>, "y": <int>, "width": <int>, "height": <int>},
           "category": "<category|null>", "key": "<key|null>",
           "mark": "<text|checkbox|circle|strike>",
           "options": [{"label": "<choice>", "box": {"x": <int>, "y": <int>, "width": <int>, "height": <int>}}]}],
 "missing": [{"name": "<label>", "question": "<question>", "category": "<category|null>",
              "key": "<key|null>", "page": <int>,
              "box": {"x": <int>, "y": <int>, "width": <int>, "height": <int>},
              "mark": "<text|checkbox|circle|strike>",
              "options": [{"label": "<choice>", "box": {"x": <int>, "y": <int>, "width": <int>, "height": <int>}}]}]}
"""


@dataclass
class OptionSpec:
    """A selectable choice for a field, with an optional box position."""

    label: str
    x: Optional[float] = None  # image px pre-conversion, PDF pts after
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None

    @property
    def box(self) -> Optional[tuple[float, float, float, float]]:
        """PDF-space rectangle (x0, y0, x1, y1) when all parts are known."""
        if None in (self.x, self.y, self.width, self.height):
            return None
        return (
            float(self.x),
            float(self.y),
            float(self.x) + float(self.width),
            float(self.y) + float(self.height),
        )


@dataclass
class FillEntry:
    name: str
    value: str
    page: Optional[int] = None
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    font_size: Optional[float] = None
    box: Optional[tuple[float, float, float, float]] = None
    category: Optional[str] = None
    key: Optional[str] = None
    options: list[OptionSpec] = field(default_factory=list)
    mark_kind: str = "text"


@dataclass
class MissingEntry:
    name: str
    question: str
    category: Optional[str] = None
    key: Optional[str] = None
    page: Optional[int] = None
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    font_size: Optional[float] = None
    box: Optional[tuple[float, float, float, float]] = None
    options: list[OptionSpec] = field(default_factory=list)
    mark_kind: str = "text"


@dataclass
class FillPlan:
    fill: list[FillEntry] = field(default_factory=list)
    missing: list[MissingEntry] = field(default_factory=list)
    used_vision: bool = False
    raw: dict = field(default_factory=dict)


def _field_list_text(info: PdfFormInfo) -> str:
    if info.fields:
        lines = [f"- {f.name} (type: {f.type})" for f in info.fields]
        return "\n".join(lines)
    # Fall back to page text for flat PDFs without fields.
    parts = []
    for i, text in enumerate(info.page_text):
        if text.strip():
            parts.append(f"--- page {i} text ---\n{text[:3000]}")
    return "\n".join(parts) or "(no extractable text)"


def _build_query(info: PdfFormInfo, data_text: str, language: str) -> str:
    return (
        f"Fill the form in language: {language}.\n\n"
        "PDF form fields:\n"
        f"{_field_list_text(info)}\n\n"
        "User data:\n"
        f"{data_text}\n\n"
        "Produce the JSON mapping now."
    )


def _coerce_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_MARK_KINDS = {"text", "checkbox", "circle", "strike"}


def _normalize_mark(raw) -> str:
    value = str(raw or "").strip().lower()
    return value if value in _MARK_KINDS else "text"


def _parse_options(raw_options) -> list[OptionSpec]:
    options: list[OptionSpec] = []
    for opt in raw_options or []:
        if isinstance(opt, str):
            if opt.strip():
                options.append(OptionSpec(label=opt.strip()))
        elif isinstance(opt, dict):
            label = str(opt.get("label", "")).strip()
            if not label:
                continue
            box = opt.get("box") if isinstance(opt.get("box"), dict) else {}
            options.append(
                OptionSpec(
                    label=label,
                    x=_coerce_float(box.get("x")),
                    y=_coerce_float(box.get("y")),
                    width=_coerce_float(box.get("width")),
                    height=_coerce_float(box.get("height")),
                )
            )
    return options


def _parse_plan(raw: dict, used_vision: bool) -> FillPlan:
    plan = FillPlan(used_vision=used_vision, raw=raw)
    for item in raw.get("fill", []) or []:
        if not isinstance(item, dict):
            continue
        box = item.get("box") if isinstance(item.get("box"), dict) else {}
        category = item.get("category")
        key = item.get("key")
        plan.fill.append(
            FillEntry(
                name=str(item.get("name", "")),
                value=str(item.get("value", "")),
                page=_coerce_int(item.get("page")),
                x=_coerce_float(box.get("x", item.get("x"))),
                y=_coerce_float(box.get("y", item.get("y"))),
                width=_coerce_float(box.get("width", item.get("width"))),
                height=_coerce_float(box.get("height", item.get("height"))),
                category=None if category is None else str(category),
                key=None if key is None else str(key),
                options=_parse_options(item.get("options")),
                mark_kind=_normalize_mark(item.get("mark")),
            )
        )
    for item in raw.get("missing", []) or []:
        if not isinstance(item, dict):
            continue
        category = item.get("category")
        key = item.get("key")
        box = item.get("box") if isinstance(item.get("box"), dict) else {}
        plan.missing.append(
            MissingEntry(
                name=str(item.get("name", "")),
                question=str(item.get("question", "")),
                category=None if category is None else str(category),
                key=None if key is None else str(key),
                page=_coerce_int(item.get("page")),
                x=_coerce_float(box.get("x", item.get("x"))),
                y=_coerce_float(box.get("y", item.get("y"))),
                width=_coerce_float(box.get("width", item.get("width"))),
                height=_coerce_float(box.get("height", item.get("height"))),
                options=_parse_options(item.get("options")),
                mark_kind=_normalize_mark(item.get("mark")),
            )
        )
    return plan


def _vision_scale(info: PdfFormInfo, max_width: float = 1100.0) -> float:
    widths = [w for w, _ in info.page_sizes] or [612.0]
    scale = max_width / max(max(widths), 1.0)
    return max(0.2, min(scale, 3.0))


def _image_rect_to_pdf(
    x: Optional[float],
    y: Optional[float],
    width: Optional[float],
    height: Optional[float],
    page: Optional[int],
    scale: float,
    page_heights: list[float],
) -> Optional[tuple[float, float, float, float]]:
    """Convert an image-pixel rect (top-left origin) to PDF (x0, y0, x1, y1)."""
    if None in (x, y, width, height) or page is None:
        return None
    page_h = page_heights[page] if 0 <= page < len(page_heights) else 0.0
    x0 = x / scale
    y_bottom = page_h - (y + height) / scale
    y_top = page_h - y / scale
    return (x0, y_bottom, x0 + width / scale, y_top)


_MIN_FONT_SIZE = 6.0
_MAX_FONT_SIZE = 11.0


def _box_to_pdf(
    x: Optional[float],
    y: Optional[float],
    width: Optional[float],
    height: Optional[float],
    page: Optional[int],
    scale: float,
    page_heights: list[float],
) -> tuple[
    Optional[float],
    Optional[float],
    Optional[int],
    Optional[float],
    Optional[tuple[float, float, float, float]],
]:
    """Convert an image-pixel box (top-left origin) to PDF placement coords.

    Returns ``(x_left_pdf, baseline_y_pdf, page, font_size, box_rect)`` where
    the baseline vertically centers the text inside the reported box and
    ``box_rect`` is the box itself in PDF points (x0, y0, x1, y1). Falls back
    to placing text just below a bare point when no box size is given.
    """
    if x is None or y is None or page is None:
        return None, None, page, None, None
    height_pdf = page_heights[page] if 0 <= page < len(page_heights) else 0.0
    x_pdf = x / scale + 2.0

    if height and height > 0:
        h_pt = height / scale
        top_pdf = height_pdf - (y + height) / scale
        bottom_pdf = height_pdf - y / scale
        center = (top_pdf + bottom_pdf) / 2.0
        font = max(_MIN_FONT_SIZE, min(_MAX_FONT_SIZE, h_pt * 0.7))
        baseline = center - font * 0.35
        box = (x_pdf - 2.0, bottom_pdf, x_pdf - 2.0 + width / scale, top_pdf)
        return x_pdf, baseline, page, font, box

    # Bare point: draw the text below the reported point.
    font = _MAX_FONT_SIZE
    baseline = height_pdf - y / scale - font
    return x_pdf, baseline, page, font, None


async def interpret_with_agent(
    info: PdfFormInfo,
    data_text: str,
    llm: LLMService,
    language: str = "en",
) -> FillPlan:
    """Interpret an AcroForm PDF using an openJiuwen ReActAgent."""
    from openjiuwen.core.foundation.tool import tool
    from openjiuwen.core.single_agent import AgentCard, ReActAgent, ReActAgentConfig

    fields_text = _field_list_text(info)

    @tool(
        name="read_pdf_fields",
        description="Return the list of fields in the PDF form.",
    )
    def read_pdf_fields() -> str:
        return fields_text

    @tool(
        name="read_data",
        description="Return the contents of the user's data file (data.md).",
    )
    def read_data() -> str:
        return data_text

    config = ReActAgentConfig(
        model_client_config=llm.model.model_client_config,
        model_config_obj=llm.model.model_config,
        prompt_template=[{"role": "system", "content": _SYSTEM_PROMPT}],
        max_iterations=6,
    )
    agent = ReActAgent(
        card=AgentCard(
            id=f"form_filler_{uuid.uuid4().hex[:12]}",
            name="form_filler",
            description="Maps user data onto PDF form fields",
        )
    ).configure(config)
    agent.ability_manager.add_ability(read_pdf_fields.card, read_pdf_fields)
    agent.ability_manager.add_ability(read_data.card, read_data)

    result = await agent.invoke({"query": _build_query(info, data_text, language)})
    output = result.get("output", "") if isinstance(result, dict) else str(result)
    raw = extract_json(output)
    plan = _parse_plan(raw, used_vision=False)
    # Anchor field/option boxes to the PDF's exact geometry so circle/strike
    # marks (and text placement on flat-style drawn boxes) work here too.
    layout = extract_layout(info.path)
    placed = _apply_layout_boxes(plan, layout)
    if placed:
        log.info("Deterministic placement used for %d field(s)", placed)
    return plan


async def interpret_with_vision(
    info: PdfFormInfo,
    data_text: str,
    llm: LLMService,
    language: str = "en",
) -> FillPlan:
    """Interpret a flat/scanned PDF by showing the model page images.

    Pages are rendered as JPEGs (small payloads) and processed in small
    batches so large documents never produce a single oversized request.
    Connection failures are retried, falling back to ``verify_ssl=False``
    (the configuration the camera project uses successfully).
    """
    base_scale = _vision_scale(info)
    page_heights = [h for _, h in info.page_sizes]
    # Deterministic layout from the PDF itself (labels + drawn boxes).
    layout: Layout = extract_layout(info.path)
    log.info(
        "PDF layout extracted: text_spans=%d rect_boxes=%d",
        len(layout.spans),
        len(layout.boxes),
    )
    # Per-page render scale: capped so no page image exceeds MAX_VISION_DIM
    # (protects against PDFs with absurd mediaboxes producing giant bitmaps).
    page_scales: dict[int, float] = {}
    for i in range(info.pages):
        width, height = (
            info.page_sizes[i] if i < len(info.page_sizes) else (612.0, 792.0)
        )
        page_scales[i] = min(
            base_scale, _MAX_VISION_DIM / max(max(width, height), 1.0)
        )

    log.info(
        "Vision interpretation: pages=%d base_scale=%.3f per_page_scales=%s",
        info.pages,
        base_scale,
        {i: round(s, 3) for i, s in sorted(page_scales.items())},
    )

    merged: dict = {"fill": [], "missing": []}
    for start in range(0, max(info.pages, 1), _VISION_PAGES_PER_CALL):
        indices = list(range(start, min(start + _VISION_PAGES_PER_CALL, info.pages)))
        images = [
            render_page_jpeg(
                info.path, page_index=i, scale=page_scales[i]
            )
            for i in indices
        ]
        total_bytes = sum(len(img) for img in images)
        log.info(
            "Vision batch pages=%s jpeg_bytes=%d", indices, total_bytes
        )
        user = _vision_user_text(
            data_text, indices, page_scales, info.page_sizes, language
        )
        text = await _complete_with_fallback(
            llm, _SYSTEM_PROMPT_VISION, user, images
        )
        raw = extract_json(text)
        for key in ("fill", "missing"):
            if isinstance(raw.get(key), list):
                merged[key].extend(raw[key])

    plan = _parse_plan(merged, used_vision=True)

    def convert(entry):
        scale = page_scales.get(entry.page if entry.page is not None else -1, base_scale)
        return _box_to_pdf(
            entry.x, entry.y, entry.width, entry.height, entry.page, scale, page_heights
        )

    def convert_option_box(opt: OptionSpec, page: Optional[int]) -> None:
        if page is None:
            return
        scale = page_scales.get(page, base_scale)
        rect = _image_rect_to_pdf(
            opt.x, opt.y, opt.width, opt.height, page, scale, page_heights
        )
        if rect is not None:
            opt.x, opt.y, opt.width, opt.height = rect

    for entry in plan.fill:
        entry.x, entry.y, entry.page, entry.font_size, entry.box = convert(entry)
        for opt in entry.options:
            convert_option_box(opt, entry.page)
    for entry in plan.missing:
        entry.x, entry.y, entry.page, entry.font_size, entry.box = convert(entry)
        for opt in entry.options:
            convert_option_box(opt, entry.page)

    # Override model-estimated coordinates with exact positions from the PDF
    # layout (eliminates the model's downward coordinate drift).
    placed = _apply_layout_boxes(plan, layout)
    if placed:
        log.info("Deterministic placement used for %d field(s)", placed)
    return plan


_VISION_PAGES_PER_CALL = 3
_MAX_VISION_DIM = 1600
_RETRIES = 3
# Delay before retry attempts 2 and 3. Transient DNS/network outages (common
# in WSL2 and corporate networks) typically last a few seconds, so back off
# instead of hammering the resolver.
_RETRY_DELAYS = (1.0, 3.0)


_MAX_BOX_DY = 30.0  # a form box may sit at most 30pt below its label
_MAX_BOX_DX = 80.0  # ... and at most 80pt to its right


def _find_box_near_label(
    layout: Layout,
    page: int,
    label_bbox: tuple[float, float, float, float],
) -> Optional["RectBox"]:
    """Find the form box directly below/right of a label bbox."""
    lx0, ly0, lx1, ly1 = label_bbox
    best = None
    best_score = float("inf")
    for box in layout.boxes:
        if box.page != page:
            continue
        if box.y1 > ly1 + 6.0:  # box must not sit above the label
            continue
        if box.y0 < ly0 - 160.0:  # not absurdly far below the label
            continue
        if box.x0 > lx1 + 450.0 or box.x1 < lx0 - 24.0:
            continue
        dx = max(0.0, box.x0 - lx0)
        if dx > _MAX_BOX_DX:
            continue
        dy = max(0.0, ly0 - box.y1)
        if dy > _MAX_BOX_DY:
            continue
        score = dx + dy * 4.0
        if score < best_score:
            best_score, best = score, box
    return best


def _padded_label_box(
    page: int, label_bbox: tuple[float, float, float, float]
) -> RectBox:
    """A small box hugging the label text (used for circle/strike marks)."""
    x0, y0, x1, y1 = label_bbox
    return RectBox(page, x0 - 2.0, y0 - 1.5, x1 + 2.0, y1 + 1.5)


def _apply_layout_boxes(plan: FillPlan, layout: Layout) -> int:
    """Replace model-estimated coordinates with exact PDF layout positions.

    Also anchors field boxes and per-option boxes to the PDF's real geometry.
    Returns the number of fields placed deterministically.
    """
    placed = 0

    def anchor_options(entry) -> None:
        for opt in entry.options:
            bbox = layout.find_label(entry.page if entry.page is not None else -1, opt.label)
            if bbox is None:
                continue
            box = _find_box_near_label(layout, entry.page, bbox)
            if box is None and entry.mark_kind in ("circle", "strike"):
                # No drawn box: circle/strike the option's own text.
                box = _padded_label_box(entry.page, bbox)
            if box is None:
                continue
            opt.x, opt.y = box.x0, box.y0
            opt.width, opt.height = box.x1 - box.x0, box.y1 - box.y0

    for entry in list(plan.fill) + list(plan.missing):
        if entry.page is None:
            continue
        anchor_options(entry)
        label_bbox = layout.find_label(entry.page, entry.name)
        if label_bbox is None:
            continue
        box = _find_box_near_label(layout, entry.page, label_bbox)
        if box is None and entry.mark_kind in ("circle", "strike"):
            # No drawn box: circle/strike the field's own label text.
            box = _padded_label_box(entry.page, label_bbox)
        if box is None:
            continue
        height = box.y1 - box.y0
        font = max(_MIN_FONT_SIZE, min(_MAX_FONT_SIZE, height * 0.7))
        entry.x = box.x0 + 2.0
        entry.y = (box.y0 + box.y1) / 2.0 - font * 0.35
        entry.font_size = font
        entry.box = (box.x0, box.y0, box.x1, box.y1)
        placed += 1
    return placed


def _vision_user_text(
    data_text: str,
    indices: list[int],
    page_scales: dict[int, float],
    page_sizes: list[tuple[float, float]],
    language: str = "en",
) -> str:
    parts = [
        f"Fill the form in language: {language}.\n\nThe user data:\n{data_text}\n"
    ]
    for image_idx, page in enumerate(indices):
        width, height = (
            page_sizes[page] if 0 <= page < len(page_sizes) else (612.0, 792.0)
        )
        scale = page_scales.get(page, 1.0)
        parts.append(
            f"Image {image_idx + 1} shows page {page} (0-based index). "
            f"Page size is {int(width * scale)}x{int(height * scale)} pixels. "
            f'Set "page": {page} for its fields.'
        )
    parts.append("Produce the JSON mapping now.")
    return "\n".join(parts)


def _is_connection_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    for fragment in (
        "apiconnectionerror",
        "connection error",
        "connecterror",
        "remote protocol error",
        "ssl",
        "tls",
    ):
        if fragment in text:
            return True
    return False


async def _complete_with_fallback(
    llm: LLMService,
    system: str,
    user: str,
    images: list[bytes],
) -> str:
    """Call the LLM, retrying transient connection failures.

    After exhausting same-config retries, falls back to ``verify_ssl=False``
    once (some networks need it, e.g. transparent TLS proxies).
    """
    last_error: BaseException | None = None
    for attempt in range(_RETRIES):
        if attempt > 0:
            delay = _RETRY_DELAYS[attempt - 1] if attempt - 1 < len(_RETRY_DELAYS) else 2.0
            log.info(
                "Retrying after %.1fs (transient connection failure)", delay
            )
            await asyncio.sleep(delay)
        try:
            return await llm.complete(system, user, images=images)
        except BaseException as exc:  # noqa: BLE001
            if not _is_connection_error(exc):
                raise
            last_error = exc
            log.warning(
                "LLM connection error (attempt %d/%d): %s",
                attempt + 1,
                _RETRIES,
                exc,
            )
            log.warning(
                "Failure traceback (attempt %d/%d):", attempt + 1, _RETRIES
            )
            log.exception(
                "LLM connection error details (attempt %d/%d)",
                attempt + 1,
                _RETRIES,
            )

    if llm.config.verify_ssl:
        import dataclasses

        fallback_cfg = dataclasses.replace(llm.config, verify_ssl=False)
        log.info("Retrying with verify_ssl=False (fallback config)")
        try:
            fallback = LLMService(fallback_cfg)
            return await fallback.complete(system, user, images=images)
        except BaseException:  # noqa: BLE001
            log.exception("verify_ssl=False fallback also failed")

    assert last_error is not None
    raise last_error


async def interpret(
    info: PdfFormInfo,
    data_text: str,
    llm_config: LLMConfig,
    language: str = "en",
) -> FillPlan:
    """Interpret a PDF form and return a fill plan."""
    llm = LLMService(llm_config)
    if info.has_fields:
        log.info(
            "Interpretation path=acroform fields=%d pages=%d language=%s",
            len(info.fields),
            info.pages,
            language,
        )
        return await interpret_with_agent(info, data_text, llm, language)
    log.info(
        "Interpretation path=vision pages=%d text_chars=%d language=%s",
        info.pages,
        sum(len(t) for t in info.page_text),
        language,
    )
    return await interpret_with_vision(info, data_text, llm, language)
