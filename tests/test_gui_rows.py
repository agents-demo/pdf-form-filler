"""Tests for the GUI summary-row logic (no Qt application needed)."""
import json

from pdffiller.agent import FillEntry, FillPlan, MissingEntry
from pdffiller.controller import FieldState, FillResult
from pdffiller.data_store import DataStore
from pdffiller.gui.main_window import MainWindow


def _plan():
    return FillPlan(
        fill=[FillEntry(name="first_name", value="Jonathan")],
        missing=[
            MissingEntry(
                name="email",
                question="Email?",
                category="personal",
                key="Email",
            )
        ],
    )


def _store(tmp_path, data=None):
    path = tmp_path / "data.json"
    path.write_text(
        json.dumps(data or {"language": "en", "personal": {"First name": "Jonathan"}}),
        encoding="utf-8",
    )
    return DataStore(path).load()


def test_state_rows_includes_missing(tmp_path):
    result = FillResult(
        plan=_plan(),
        output_path="x.pdf",
        states={"first_name": FieldState(name="first_name", value="Jonathan")},
    )
    rows = MainWindow._state_rows(result, _store(tmp_path))
    assert [(s.name, s.value) for s in rows] == [
        ("first_name", "Jonathan"),
        ("email", ""),
    ]
    assert rows[1].category == "personal"
    assert rows[1].key == "Email"


def test_state_rows_missing_already_resolved(tmp_path):
    result = FillResult(
        plan=_plan(),
        output_path="x.pdf",
        states={
            "first_name": FieldState(name="first_name", value="Jonathan"),
            "email": FieldState(name="email", value="j@example.com"),
        },
    )
    rows = MainWindow._state_rows(result, _store(tmp_path))
    assert [(s.name, s.value) for s in rows] == [
        ("first_name", "Jonathan"),
        ("email", "j@example.com"),
    ]


def test_state_rows_seeds_saved_options_for_unresolved(tmp_path):
    data = {
        "language": "en",
        "personal": {"Email": {"value": "a@b.com", "options": ["a@b.com", "b@c.com"]}},
    }
    result = FillResult(
        plan=_plan(),
        output_path="x.pdf",
        states={"first_name": FieldState(name="first_name", value="Jonathan")},
    )
    rows = MainWindow._state_rows(result, _store(tmp_path, data))
    email = next(s for s in rows if s.name == "email")
    assert email.options == ["a@b.com", "b@c.com"]
