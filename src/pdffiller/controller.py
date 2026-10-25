"""Orchestration: inspect -> interpret -> prompt for missing -> fill.

Kept GUI-free so the whole flow can be unit-tested with a fake prompter.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional

from .agent import FillPlan, OptionSpec, interpret
from .config import LLMConfig
from .data_store import DataStore
from .pdf_fill import Placement, fill_pdf
from .pdf_inspect import inspect_pdf

log = logging.getLogger(__name__)


@dataclass
class PromptRequest:
    name: str
    question: str
    suggested_category: Optional[str] = None
    suggested_key: Optional[str] = None
    options: list[str] = field(default_factory=list)


@dataclass
class PromptResult:
    value: str
    category: Optional[str] = None
    key: Optional[str] = None
    options: list[str] = field(default_factory=list)


@dataclass
class FieldState:
    """One field's value, options and rendering mode."""

    name: str
    value: str = ""
    category: str = "personal"
    key: str = ""
    options: list[str] = field(default_factory=list)
    option_boxes: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)
    mark: str = "text"  # text | x | check | circle | strike
    mark_kind: str = "text"  # designation from the form: text|checkbox|circle|strike
    page: Optional[int] = None
    x: Optional[float] = None  # text baseline (fallback when no box)
    y: Optional[float] = None
    box: Optional[tuple[float, float, float, float]] = None
    font_size: Optional[float] = None
    is_checkbox: bool = False


# Default mark used for the initial fill, per form designation.
_KIND_DEFAULT_MARK = {
    "text": "text",
    "checkbox": "x",
    "circle": "circle",
    "strike": "strike",
}


@dataclass
class PlacementSpec:
    name: str
    page: int
    x: float
    y: float
    font_size: float | None = None
    mark: str = ""
    box: Optional[tuple[float, float, float, float]] = None


@dataclass
class FillResult:
    plan: FillPlan
    output_path: str
    states: dict[str, FieldState] = None
    placement_specs: list["PlacementSpec"] = None

    def __post_init__(self):
        if self.states is None:
            self.states = {}
        if self.placement_specs is None:
            self.placement_specs = []

    @property
    def resolved(self) -> dict[str, str]:
        """Field name -> final value (backwards-compatible view)."""
        return {name: state.value for name, state in self.states.items()}


PromptFn = Callable[[PromptRequest], Awaitable[Optional[PromptResult]]]

_TEXT_MARKS = ("text", "")


def seed_state_options(data_store: DataStore, state: FieldState) -> None:
    """Merge options previously saved in the data file into ``state``."""
    saved = data_store.get_options(state.key) or data_store.get_options(state.name)
    for option in saved:
        if option not in state.options:
            state.options.append(option)


class FillController:
    """Drive the end-to-end form-filling flow."""

    def __init__(
        self,
        llm_config: LLMConfig,
        data_store: DataStore,
        prompt_fn: PromptFn,
    ):
        self.llm_config = llm_config
        self.data_store = data_store
        self.prompt_fn = prompt_fn

    async def run(self, pdf_path: str | Path) -> FillResult:
        log.info("Fill started: pdf=%s", pdf_path)
        info = inspect_pdf(pdf_path)
        log.info(
            "Inspect result: pages=%d fields=%d is_form=%s",
            info.pages,
            len(info.fields),
            info.has_fields,
        )
        field_types = {f.name: f.type for f in info.fields}
        self.data_store.load()
        data_text = self.data_store.to_text()

        plan: FillPlan = await interpret(
            info, data_text, self.llm_config, self.data_store.language
        )
        log.info(
            "Plan: fill=%d missing=%d used_vision=%s",
            len(plan.fill),
            len(plan.missing),
            plan.used_vision,
        )

        states: dict[str, FieldState] = {}
        for entry in plan.fill:
            states[entry.name] = self._state_from_entry(
                entry, entry.value, field_types
            )

        # Ask the user for each missing value.
        for entry in plan.missing:
            answer = await self.prompt_fn(
                PromptRequest(
                    name=entry.name,
                    question=entry.question or f"What is the value for '{entry.name}'?",
                    suggested_category=entry.category,
                    suggested_key=entry.key,
                    options=[o.label for o in entry.options],
                )
            )
            if answer is None or not answer.value.strip():
                log.info("Missing field skipped (no answer): %s", entry.name)
                continue  # user cancelled / left blank -> skip this field

            value = answer.value.strip()
            category = (answer.category or entry.category or "personal").strip()
            key = (answer.key or entry.key or entry.name).strip()
            state = self._state_from_entry(entry, value, field_types)
            state.category = category
            state.key = key
            answer_options = getattr(answer, "options", None)
            if answer_options:
                state.options = list(answer_options)
            states[entry.name] = state

        # Merge in the options the user saved previously so they are never
        # silently lost on a fresh fill.
        for state in states.values():
            seed_state_options(self.data_store, state)

        # Save every filled field (values + options + language) to data.json.
        self.save_states(list(states.values()))

        output_path = self.apply_fixes(pdf_path, list(states.values()))
        log.info(
            "Fill complete: output=%s fields=%d", output_path, len(states)
        )
        return FillResult(
            plan=plan,
            output_path=output_path,
            states=states,
            placement_specs=self._placement_specs(states),
        )

    @staticmethod
    def _state_from_entry(entry, value: str, field_types: dict[str, str]) -> FieldState:
        is_checkbox = field_types.get(entry.name) == "checkbox"
        mark_kind = entry.mark_kind
        if is_checkbox and mark_kind == "text":
            mark_kind = "checkbox"
        return FieldState(
            name=entry.name,
            value=value,
            category=(entry.category or "personal").strip() if entry.category else "personal",
            key=(entry.key or entry.name).strip() if entry.key else entry.name,
            options=[o.label for o in entry.options],
            option_boxes={
                o.label: o.box for o in entry.options if o.box is not None
            },
            mark=_KIND_DEFAULT_MARK.get(mark_kind, "text"),
            mark_kind=mark_kind,
            page=entry.page,
            x=entry.x,
            y=entry.y,
            box=entry.box,
            font_size=entry.font_size,
            is_checkbox=is_checkbox,
        )

    @staticmethod
    def _placement_specs(states: dict[str, FieldState]) -> list[PlacementSpec]:
        specs: list[PlacementSpec] = []
        for state in states.values():
            if state.page is None:
                continue
            specs.append(
                PlacementSpec(
                    name=state.name,
                    page=state.page,
                    x=state.box[0] + 2.0 if state.box else 0.0,
                    y=state.box[1] + 2.0 if state.box else 0.0,
                    font_size=state.font_size,
                    mark=state.mark,
                    box=state.box,
                )
            )
        return specs

    def apply_fixes(self, pdf_path: str | Path, states: list[FieldState]) -> str:
        """Re-fill the PDF using the (edited) field states.

        Text values fill AcroForm fields / overlay text; marks are rendered
        as overlay symbols inside the field's box (or the chosen option's
        box). Returns the output path.
        """
        info = inspect_pdf(pdf_path)
        mapping: dict[str, str] = {}
        placements: list[Placement] = []

        for state in states:
            if not state.value.strip() and state.mark in _TEXT_MARKS:
                continue
            target_box = self._target_box(state)
            if state.mark in _TEXT_MARKS:
                if info.has_fields and not state.is_checkbox:
                    mapping[state.name] = state.value
                else:
                    text = self._text_placement(state)
                    if text is not None:
                        placements.append(text)
            elif state.mark in ("x", "check"):
                if info.has_fields and state.is_checkbox:
                    mapping[state.name] = "X" if state.mark == "x" else "✓"
                if target_box is not None:
                    placements.append(self._mark_placement(state, target_box))
            else:  # circle / strike
                if target_box is not None:
                    placements.append(self._mark_placement(state, target_box))

        output = fill_pdf(
            pdf_path,
            mapping=mapping or None,
            placements=placements or None,
        )
        log.info(
            "Fixes applied: output=%s mapping=%d marks=%d",
            output,
            len(mapping),
            sum(1 for p in placements if p.mark),
        )
        return output

    @staticmethod
    def _target_box(state: FieldState) -> Optional[tuple[float, float, float, float]]:
        """Box to render the mark in: the chosen option's box if available."""
        if state.value and state.value in state.option_boxes:
            return state.option_boxes[state.value]
        return state.box

    @staticmethod
    def _text_placement(state: FieldState) -> Optional[Placement]:
        font = state.font_size or 10.0
        page = state.page if state.page is not None else 0
        if state.box is not None:
            x0, y0, _x1, y1 = state.box
            baseline = (y0 + y1) / 2.0 - font * 0.35
            return Placement(
                page=page, x=x0 + 2.0, y=baseline, value=state.value, font_size=font
            )
        if state.x is not None and state.y is not None:
            return Placement(
                page=page, x=state.x, y=state.y, value=state.value, font_size=font
            )
        return None

    @staticmethod
    def _mark_placement(
        state: FieldState, box: tuple[float, float, float, float]
    ) -> Placement:
        x0, y0, x1, y1 = box
        return Placement(
            page=state.page if state.page is not None else 0,
            x=x0,
            y=y0,
            value=state.value,
            font_size=state.font_size,
            mark=state.mark,
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
        )

    def save_states(self, states: list[FieldState]) -> None:
        """Persist all field values and options into the data file.

        Existing saved options are preserved unless the state itself carries
        a new option list (i.e. the user explicitly changed them) — options
        are only erased by an explicit user edit.
        """
        if not self.data_store.is_loaded:
            self.data_store.load()
        for state in states:
            options = list(state.options)
            if not options:
                # Never erase saved options implicitly: keep them.
                saved = self.data_store.get_options(
                    state.key, state.category
                ) or self.data_store.get_options(state.name)
                if saved:
                    options = list(saved)
            if not state.value.strip() and not options:
                continue
            self.data_store.upsert(
                state.category or "personal",
                state.key or state.name,
                state.value,
                options=options or None,
            )
        self.data_store.save()
        log.info("Saved %d field(s) to %s", len(states), self.data_store.path)
