"""Tests for the fixes flow: marks, choices and data.json persistence."""
import json

from pdffiller.config import LLMConfig
from pdffiller.controller import FieldState, FillController
from pdffiller.data_store import DataStore


def _controller(tmp_path):
    data_path = tmp_path / "data.json"
    data_path.write_text(
        json.dumps({"language": "en", "personal": {"First name": "Jonathan"}}),
        encoding="utf-8",
    )
    return FillController(
        llm_config=LLMConfig(api_key="test"),
        data_store=DataStore(data_path),
        prompt_fn=None,
    )


def test_apply_fixes_text_and_marks(flat_form, tmp_path):
    controller = _controller(tmp_path)
    box = (70.0, 676.0, 370.0, 698.0)
    states = [
        FieldState(name="First name", value="Jonathan", page=0, box=box, font_size=11.0),
        FieldState(name="Consent", value="Yes", page=0, mark="x", box=box),
        FieldState(name="Old option", value="Yes", page=0, mark="strike", box=box),
    ]
    output = controller.apply_fixes(flat_form, states)
    assert output.endswith("_filled.pdf")


def test_apply_fixes_circle_targets_chosen_option_box(flat_form, tmp_path):
    controller = _controller(tmp_path)
    field_box = (70.0, 676.0, 370.0, 698.0)
    option_box = (400.0, 676.0, 430.0, 698.0)
    state = FieldState(
        name="Gender",
        value="Male",
        page=0,
        mark="circle",
        box=field_box,
        option_boxes={"Male": option_box},
    )
    output = controller.apply_fixes(flat_form, [state])
    assert output.endswith("_filled.pdf")


def test_save_states_persists_values_and_options(tmp_path):
    controller = _controller(tmp_path)
    states = [
        FieldState(
            name="Gender",
            value="Female",
            category="personal",
            key="Gender",
            options=["Male", "Female", "Other"],
        ),
        FieldState(
            name="City",
            value="Tel Aviv",
            category="personal",
            key="City",
        ),
    ]
    controller.save_states(states)
    reloaded = DataStore(controller.data_store.path).load()
    assert reloaded.get("Gender", "personal") == "Female"
    assert reloaded.get_options("Gender", "personal") == ["Male", "Female", "Other"]
    assert reloaded.get("City", "personal") == "Tel Aviv"


def test_save_states_skips_empty(tmp_path):
    controller = _controller(tmp_path)
    controller.save_states([FieldState(name="Empty", value="", category="personal")])
    reloaded = DataStore(controller.data_store.path).load()
    assert reloaded.get("Empty", "personal") is None


def test_default_mark_from_designation():
    from pdffiller.agent import FillEntry

    expected = {"text": "text", "checkbox": "x", "circle": "circle", "strike": "strike"}
    for kind, mark in expected.items():
        entry = FillEntry(name="f", value="v", mark_kind=kind)
        state = FillController._state_from_entry(entry, "v", {})
        assert state.mark == mark
        assert state.mark_kind == kind


def test_mark_choices_filtered_by_designation():
    from pdffiller.gui.main_window import _MARK_CHOICES

    assert [m for _, m in _MARK_CHOICES["text"]] == ["text"]
    assert [m for _, m in _MARK_CHOICES["checkbox"]] == ["text", "x", "check"]
    assert [m for _, m in _MARK_CHOICES["circle"]] == ["text", "circle"]
    assert [m for _, m in _MARK_CHOICES["strike"]] == ["text", "strike"]


def test_save_states_preserves_language_change(tmp_path):
    controller = _controller(tmp_path)
    controller.data_store.load()
    controller.data_store.set_language("he")
    controller.save_states([FieldState(name="City", value="Tel Aviv", category="personal")])
    reloaded = DataStore(controller.data_store.path).load()
    assert reloaded.language == "he"
    assert reloaded.get("City", "personal") == "Tel Aviv"


def test_save_states_preserves_existing_options(tmp_path):
    """A fresh fill must not erase options saved previously."""
    controller = _controller(tmp_path)
    controller.data_store.load()
    controller.data_store.upsert(
        "personal", "Gender", "Male", options=["Male", "Female", "Other"]
    )
    controller.data_store.save()

    # New state has no options (agent did not report any).
    controller.save_states([FieldState(name="Gender", value="Female", category="personal")])
    reloaded = DataStore(controller.data_store.path).load()
    assert reloaded.get("Gender", "personal") == "Female"
    assert reloaded.get_options("Gender", "personal") == ["Male", "Female", "Other"]


def test_save_states_replaces_options_when_explicitly_given(tmp_path):
    controller = _controller(tmp_path)
    controller.data_store.load()
    controller.data_store.upsert(
        "personal", "Gender", "Male", options=["Male", "Female", "Other"]
    )
    controller.data_store.save()

    # Explicit user edit: new option list replaces the old one.
    controller.save_states(
        [FieldState(name="Gender", value="Other", category="personal",
                    options=["Female", "Other"])]
    )
    reloaded = DataStore(controller.data_store.path).load()
    assert reloaded.get_options("Gender", "personal") == ["Female", "Other"]


def test_seed_state_options_merges_saved_options(tmp_path):
    from pdffiller.controller import seed_state_options

    controller = _controller(tmp_path)
    controller.data_store.load()
    controller.data_store.upsert(
        "personal", "First name", "Yoni", options=["Jonathan", "Yoni"]
    )
    state = FieldState(name="First name", value="Yoni", category="personal")
    seed_state_options(controller.data_store, state)
    assert state.options == ["Jonathan", "Yoni"]
