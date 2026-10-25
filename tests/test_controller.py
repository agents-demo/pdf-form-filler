import json

import pytest

from pdffiller.agent import FillEntry, FillPlan, MissingEntry
from pdffiller.config import LLMConfig
from pdffiller.controller import FillController
from pdffiller.data_store import DataStore
from pdffiller.pdf_inspect import inspect_pdf


def _make_plan():
    return FillPlan(
        fill=[FillEntry(name="first_name", value="Jonathan")],
        missing=[
            MissingEntry(
                name="email",
                question="What is your email?",
                category="personal",
                key="Email",
            )
        ],
        used_vision=False,
    )


def _write_data(path, data=None):
    path.write_text(
        json.dumps(data or {"language": "en", "personal": {"First name": "Jonathan"}}),
        encoding="utf-8",
    )


async def test_controller_end_to_end(fillable_form, tmp_path, monkeypatch):
    data_path = tmp_path / "data.json"
    _write_data(data_path)

    # Avoid calling the real LLM.
    async def fake_interpret(info, data_text, llm_config, language="en"):
        return _make_plan()

    monkeypatch.setattr("pdffiller.controller.interpret", fake_interpret)

    prompted = []

    async def fake_prompt(request):
        prompted.append(request)
        return type(
            "Answer", (), {"value": "j@example.com", "category": "personal", "key": "Email"}
        )()

    controller = FillController(
        llm_config=LLMConfig(api_key="test"),
        data_store=DataStore(data_path),
        prompt_fn=fake_prompt,
    )
    result = await controller.run(fillable_form)

    assert len(prompted) == 1
    assert prompted[0].name == "email"
    assert result.resolved == {"first_name": "Jonathan", "email": "j@example.com"}

    # The values were written back to data.json (all fields, not just missing).
    reloaded = DataStore(data_path).load()
    assert reloaded.get("Email", "personal") == "j@example.com"
    assert reloaded.get("first_name", "personal") == "Jonathan"

    # The output PDF now contains both values.
    info = inspect_pdf(result.output_path)
    values = {f.name: f.value for f in info.fields}
    assert values["first_name"] == "Jonathan"
    assert values["email"] == "j@example.com"


async def test_controller_skips_cancelled(fillable_form, tmp_path, monkeypatch):
    data_path = tmp_path / "data.json"
    _write_data(data_path)

    async def fake_interpret(info, data_text, llm_config, language="en"):
        return _make_plan()

    monkeypatch.setattr("pdffiller.controller.interpret", fake_interpret)

    async def fake_prompt(request):
        return None  # user cancels

    controller = FillController(
        llm_config=LLMConfig(api_key="test"),
        data_store=DataStore(data_path),
        prompt_fn=fake_prompt,
    )
    result = await controller.run(fillable_form)
    assert result.resolved == {"first_name": "Jonathan"}
