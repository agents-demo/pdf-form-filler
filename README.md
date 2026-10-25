# PDF Form Filler

GUI software that fills PDF forms from a hierarchical `data.md` file, using the
[openJiuwen agent-core](https://github.com/openJiuwen-ai/agent-core) library.

## Features

- Reads a hierarchical `data.json` file (`language` heading + categories with
  field entries; each entry is a value string or `{"value", "options"}`):
  ```json
  {
    "language": "en",
    "personal": {
      "First name": "Yoni",
      "Gender": {"value": "Male", "options": ["Male", "Female", "Other"]}
    }
  }
  ```
- Interprets a PDF form and produces a filled PDF:
  - **AcroForm PDFs** (with fillable fields) are interpreted by an openJiuwen
    `ReActAgent` with `read_pdf_fields` / `read_data` tools.
  - **Flat/scanned PDFs** are interpreted by openJiuwen's `Model` with the
    rendered page images attached (vision) — use a vision-capable model such as
    `deepseek-v4-flash-vision-exp`.
- For missing items, asks the user for the value (and category).
- **Everything is saved to `data.json`** — every fill (including the first
  one) writes all filled values, options and the language heading back to the
  data file.
- Shows the filled PDF and lets the user fix fields before saving:
  - **Options for every field** — each field's value is a dropdown of its
    options; the **Edit…** button per field opens a manager to **add,
    rename or delete** options (e.g. name can be "Jonathan" or "Yoni").
    Typing a new value in the dropdown also adds it as an option.
  - **Marks only where the form designates them** — the agent reads the form's
    instructions (tick/check, circle, cross out). Each field's Mark menu then
    offers only what the form allows: **X / ✓** for tick-designated fields,
    **circle** for circle-designated fields, **strikethrough** for
    cross-out-designated fields; other fields stay text-only.
  - **Apply Fixes** re-fills the PDF and saves the updated values, options
    and language back into `data.json` (gitignored).
- **Language support** — the `language` heading in `data.json` selects the
  fill language; the app passes it to the model and it can be changed in the
  GUI (saved on fill/fixes).

## Setup

```bash
uv sync
cp .env.example .env   # then fill in DEEPSEEK_API_KEY
```

Python 3.11–3.13 is required (the project targets 3.11–3.13; `uv` uses 3.12).

## Run

```bash
uv run python -m pdffiller
```

The LLM endpoint defaults to the DeepSeek OpenAI-compatible API
(`https://api.deepseek.com`, provider `OpenAI`, model
`deepseek-v4-flash-vision-exp` — vision-capable). Override any value in `.env`
or via the in-app **Settings** dialog.

## Generate sample forms

```bash
uv run python scripts/make_sample_form.py
```

This writes `sample/sample_form.pdf` (fillable AcroForm with text fields and
checkboxes) and `sample/sample_flat.pdf` (flat, for the vision path). Both
include mark sections to exercise the mark features: a **tick (X)** section,
a **circle the correct answer** section, and a **cross out / strikethrough**
section.

## Test

```bash
uv run pytest
```

## Logs

The app writes a detailed log to `logs/pdffiller.log` (rotating, ~2 MB × 3).
It records every step of a fill — PDF inspection, LLM requests (image byte
sizes, masked API key), retries, and full exception cause chains — so
connection failures can be diagnosed. The error dialog also points to this
file.

## Project layout

```
src/pdffiller/
  config.py        # LLM/app settings, .env load/save
  data_store.py    # hierarchical data.json read/update (values + options + language)
  pdf_inspect.py   # extract AcroForm fields, page text, geometry
  pdf_fill.py      # AcroForm filling + flat-PDF text/mark overlay
  pdf_layout.py    # exact label/box positions extracted from the PDF
  pdf_render.py    # page -> PNG rendering
  llm.py           # openJiuwen Model wrapper (text + vision)
  agent.py         # ReActAgent + vision interpretation -> FillPlan
  controller.py    # orchestration (inspect -> interpret -> prompt -> fill/fixes)
  _shiboken_patch.py  # PySide6 import-hook workaround for openjiuwen
  gui/             # PySide6 UI
scripts/make_sample_form.py
tests/
```

## Known upstream incompatibility (already worked around)

PySide6 (shiboken) inspects every imported module with `inspect.getsource`,
which probes `module.__wrapped__`. openjiuwen's lazy PEP 562 packages (e.g.
`openjiuwen.core.foundation.store`) treat unknown attributes as submodule
imports and raise `ModuleNotFoundError` for that probe. `_shiboken_patch.py`
applies a targeted fix at startup so the two libraries work together.

## Direct connection (no proxy)

All LLM requests connect directly to the API endpoint. Inherited
`HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` environment variables are cleared at
startup (shell-configured corporate proxies often do not resolve from WSL2,
which made every request fail with "Name or service not known"); no proxy is
ever used. Connection failures are retried with backoff.

