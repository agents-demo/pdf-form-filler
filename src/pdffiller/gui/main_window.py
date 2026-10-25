"""Main application window."""
from __future__ import annotations

import asyncio
import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig, save_to_env
from ..controller import (
    FillController,
    FieldState,
    FillResult,
    PromptRequest,
    PromptResult,
    seed_state_options,
)
from ..data_store import DataStore
from ..llm import LLMError
from ..logging_setup import get_log_path
from ..pdf_inspect import inspect_pdf
from ..pdf_render import page_count, render_page_png
from .prompt_dialog import PromptDialog
from .settings_dialog import SettingsDialog

log = logging.getLogger(__name__)

# Allowed mark renderings per field designation (from the form's instructions).
_MARK_CHOICES: dict[str, list[tuple[str, str]]] = {
    "text": [("Text", "text")],
    "checkbox": [("Text", "text"), ("X", "x"), ("✓", "check")],
    "circle": [("Text", "text"), ("Circle", "circle")],
    "strike": [("Text", "text"), ("Strike", "strike")],
}

_LANGUAGES = ["en", "he", "ar", "ru", "de", "fr", "es", "zh"]


def save_filled_copy(source: str, target: str) -> None:
    """Copy ``source`` to ``target``; no-op when they are the same file."""
    import os
    import shutil

    source_abs = os.path.abspath(source)
    target_abs = os.path.abspath(target)
    if source_abs == target_abs:
        return  # already saved there; avoid SameFileError
    try:
        if os.path.exists(target_abs) and os.path.samefile(source_abs, target_abs):
            return
    except OSError:
        pass
    shutil.copyfile(source_abs, target_abs)


class MainWindow(QMainWindow):
    def __init__(self, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.loop = loop
        self.app_config = AppConfig.from_env()
        self.data_store = DataStore(self.app_config.data_path)
        self.pdf_path: str | None = None
        self.info = None
        self.filled_path: str | None = None
        self.last_result: FillResult | None = None

        self._preview_path: str | None = None
        self._page = 0
        self._pages = 0
        self._zoom = 1.5

        self.setWindowTitle("PDF Form Filler")
        self.resize(1200, 800)
        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        open_action = QAction("Open PDF…", self)
        open_action.triggered.connect(self.open_pdf)
        toolbar.addAction(open_action)

        fill_action = QAction("Fill Form", self)
        fill_action.triggered.connect(self.start_fill)
        toolbar.addAction(fill_action)

        refill_action = QAction("Apply Fixes", self)
        refill_action.triggered.connect(self.apply_fixes)
        toolbar.addAction(refill_action)

        save_action = QAction("Save Filled As…", self)
        save_action.triggered.connect(self.save_as)
        toolbar.addAction(save_action)

        toolbar.addSeparator()
        settings_action = QAction("Settings…", self)
        settings_action.triggered.connect(self.open_settings)
        toolbar.addAction(settings_action)

        splitter = QSplitter(Qt.Horizontal)

        # Left: PDF preview
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_label = QLabel("Open a PDF to begin.")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_scroll.setWidget(self.preview_label)
        preview_layout.addWidget(self.preview_scroll, stretch=1)
        self.page_label = QLabel("Page 0 / 0")
        preview_layout.addWidget(self.page_label)
        splitter.addWidget(preview_widget)

        # Right: summary table
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        language_row = QHBoxLayout()
        language_row.addWidget(QLabel("Language:"))
        self.language_combo = QComboBox()
        self.language_combo.setEditable(True)
        self.language_combo.addItems(_LANGUAGES)
        self.language_combo.setCurrentText(self.data_store.language)
        language_row.addWidget(self.language_combo)
        language_row.addStretch(1)
        right_layout.addLayout(language_row)
        right_layout.addWidget(
            QLabel("Fields (pick a choice, manage options, choose a mark):")
        )
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Field", "Value", "Mark", "Options"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        right_layout.addWidget(self.table)
        splitter.addWidget(right_widget)

        splitter.setSizes([820, 380])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("Ready")

    # ------------------------------------------------------------- actions
    def open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PDF form", "", "PDF files (*.pdf)"
        )
        if not path:
            return
        self.pdf_path = path
        self.info = inspect_pdf(path)
        log.info(
            "Opened pdf=%s pages=%d fields=%d is_form=%s",
            path,
            self.info.pages,
            len(self.info.fields),
            self.info.has_fields,
        )
        self._show_pdf(path)
        self._update_table_for_info()
        self.statusBar().showMessage(
            f"Loaded {path} ({self.info.pages} page(s), "
            f"{'form' if self.info.has_fields else 'no form fields'})"
        )

    def start_fill(self):
        if not self.pdf_path:
            QMessageBox.information(self, "No PDF", "Open a PDF form first.")
            return
        if not self.app_config.llm.configured():
            self._prompt_for_key()
            return
        self.loop.create_task(self._run_fill())

    def _prompt_for_key(self):
        QMessageBox.information(
            self,
            "API key required",
            "No API key is configured. Open Settings and set your "
            "DEEPSEEK_API_KEY, or add it to the .env file.",
        )
        self.open_settings()

    async def _run_fill(self):
        log.info(
            "Fill requested: pdf=%s llm=%s@%s key=%s",
            self.pdf_path,
            self.app_config.llm.model,
            self.app_config.llm.api_base,
            "configured" if self.app_config.llm.configured() else "MISSING",
        )
        self.statusBar().showMessage("Interpreting PDF…")
        self.setEnabled(False)
        try:
            controller = FillController(
                self.app_config.llm, self.data_store, self._prompt
            )
            result = await controller.run(self.pdf_path)
            self.last_result = result
            self.filled_path = result.output_path
            self._show_pdf(result.output_path)
            self._update_table_for_result(result)
            missing_left = [
                m.name
                for m in result.plan.missing
                if m.name not in result.resolved
            ]
            if missing_left:
                self.statusBar().showMessage(
                    f"Done. Skipped (no answer): {', '.join(missing_left)}"
                )
            else:
                self.statusBar().showMessage(
                    f"Done. Filled PDF written to {result.output_path}"
                )
        except LLMError as exc:
            log.exception("LLM error during fill")
            QMessageBox.critical(self, "LLM error", str(exc))
            self.statusBar().showMessage("Error")
        except Exception as exc:  # noqa: BLE001
            log.exception("Error during fill")
            QMessageBox.critical(
                self,
                "Error",
                self._friendly_error(exc),
            )
            self.statusBar().showMessage("Error")
        finally:
            self.setEnabled(True)

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        """Add a hint to the raw error when it is a known failure mode."""
        text = str(exc)
        lowered = text.lower()
        # Build the full cause chain (often holds the real network error).
        causes: list[str] = []
        cause = exc.__cause__
        while cause is not None:
            causes.append(f"{type(cause).__name__}: {cause}")
            cause = cause.__cause__
        chain_text = (text + "\n" + "\n".join(causes)).lower()

        if "authentication" in lowered or "401" in lowered or "invalid api key" in lowered:
            text = (
                "The LLM provider rejected the API key.\n\n"
                "Open Settings and check DEEPSEEK_API_KEY (or the .env file).\n\n"
                f"Details:\n{text}"
            )
        elif "name or service not known" in chain_text or "getaddrinfo" in chain_text:
            text = (
                "The LLM provider's address could not be resolved (DNS).\n\n"
                "This is usually a transient network problem (common in WSL2 "
                "and corporate networks). The app retries automatically; if "
                "this message still appears, check your network/VPN and "
                "click Fill again.\n\n"
                f"Details:\n{text}"
            )
        elif "connection" in lowered:
            text = (
                "Could not reach the LLM provider. Check your network "
                "connection and retry.\n\n"
                f"Details:\n{text}"
            )
        for cause_text in causes:
            text += f"\nCaused by: {cause_text}"
        log_path = get_log_path()
        if log_path is not None:
            text += f"\n\nLog file: {log_path}"
        return text

    async def _prompt(self, request: PromptRequest) -> PromptResult | None:
        dlg = PromptDialog(self, request, self.data_store.section_titles())
        future = self.loop.create_future()

        def on_submit(value, category, key):
            if not future.done():
                future.set_result(
                    PromptResult(value, category=category or None, key=key or None)
                )

        def on_cancel():
            if not future.done():
                future.set_result(None)

        dlg.submitted.connect(on_submit)
        dlg.rejected.connect(on_cancel)
        dlg.show()
        return await future

    def apply_fixes(self):
        if not self.last_result:
            QMessageBox.information(self, "Nothing to fix", "Fill a form first.")
            return
        states = self._read_states()
        if not states:
            QMessageBox.information(self, "Nothing to fix", "No fields to apply.")
            return
        try:
            controller = FillController(
                self.app_config.llm, self.data_store, self._prompt
            )
            # Language heading from the selector.
            self.data_store.set_language(
                self.language_combo.currentText().strip() or "en"
            )
            output = controller.apply_fixes(self.pdf_path, states)
            # Persist every field's value and options into data.json.
            controller.save_states(states)
            self.filled_path = output
            self._show_pdf(output)
            self.last_result.states = {s.name: s for s in states}
            self._update_table_for_result(self.last_result)
            self.statusBar().showMessage(
                f"Fixes applied and saved to {self.data_store.path}: {output}"
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("Apply fixes failed")
            QMessageBox.critical(self, "Error", str(exc))

    def save_as(self):
        if not self.filled_path:
            QMessageBox.information(self, "Nothing to save", "Fill a form first.")
            return
        target, _ = QFileDialog.getSaveFileName(
            self, "Save filled PDF", "filled.pdf", "PDF files (*.pdf)"
        )
        if not target:
            return
        try:
            save_filled_copy(self.filled_path, target)
            self.filled_path = target
            self.statusBar().showMessage(f"Saved to {target}")
        except Exception as exc:  # noqa: BLE001
            log.exception("Save failed")
            QMessageBox.critical(self, "Error", f"Could not save the file:\n{exc}")

    def open_settings(self):
        dlg = SettingsDialog(self, self.app_config.llm)
        if dlg.exec():
            self.app_config.llm = dlg.config()
            save_to_env(self.app_config.llm)

    # ------------------------------------------------------------- helpers
    def _show_pdf(self, path: str):
        self._preview_path = path
        self._pages = page_count(path)
        self._page = 0
        self._render_preview()

    def _render_preview(self):
        if not self._preview_path:
            return
        try:
            data = render_page_png(
                self._preview_path, page_index=self._page, scale=self._zoom
            )
            pixmap = QPixmap()
            pixmap.loadFromData(data, "PNG")
            self.preview_label.setPixmap(pixmap)
            self.preview_label.resize(pixmap.size())
            self.page_label.setText(f"Page {self._page + 1} / {self._pages}")
        except Exception as exc:  # noqa: BLE001
            self.preview_label.setText(f"Preview error: {exc}")

    def _update_table_for_info(self):
        self.table.setRowCount(0)
        if not self.info:
            return
        for field in self.info.fields:
            self._add_table_row(field.name, field.value)

    def _update_table_for_result(self, result: FillResult):
        self.table.setRowCount(0)
        for state in self._state_rows(result, self.data_store):
            self._add_state_row(state)

    @staticmethod
    def _state_rows(result: FillResult, data_store: DataStore) -> list[FieldState]:
        """Flatten a fill result into editable field states."""
        rows = list(result.states.values())
        for entry in result.plan.missing:
            if entry.name not in result.states:
                state = FieldState(
                    name=entry.name,
                    value="",
                    category=entry.category or "personal",
                    key=entry.key or entry.name,
                    options=[o.label for o in entry.options],
                    option_boxes={
                        o.label: o.box for o in entry.options if o.box is not None
                    },
                    page=entry.page,
                    x=entry.x,
                    y=entry.y,
                    box=entry.box,
                    font_size=entry.font_size,
                )
                # Keep previously saved options visible in the dropdown.
                seed_state_options(data_store, state)
                rows.append(state)
        return rows

    def _add_state_row(self, state: FieldState):
        row = self.table.rowCount()
        self.table.insertRow(row)
        name_item = QTableWidgetItem(state.name)
        if not state.value.strip():
            name_item.setForeground(Qt.red)
        self.table.setItem(row, 0, name_item)

        # Value: editable dropdown of the field's options (any field).
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems(state.options)
        if state.value:
            combo.setCurrentText(state.value)
        self.table.setCellWidget(row, 1, combo)

        mark_combo = QComboBox()
        for label, mark in _MARK_CHOICES.get(state.mark_kind, _MARK_CHOICES["text"]):
            mark_combo.addItem(label, mark)
        index = mark_combo.findData(state.mark)
        mark_combo.setCurrentIndex(index if index >= 0 else 0)
        self.table.setCellWidget(row, 2, mark_combo)

        options_button = QPushButton("Edit…")
        options_button.clicked.connect(
            lambda _=False, r=row: self._edit_options(r)
        )
        self.table.setCellWidget(row, 3, options_button)

    def _edit_options(self, row: int):
        """Open the options manager for a row and refresh its dropdown."""
        from .options_dialog import OptionsDialog

        combo = self.table.cellWidget(row, 1)
        if not isinstance(combo, QComboBox):
            return
        current = combo.currentText().strip()
        options = [
            combo.itemText(i) for i in range(combo.count()) if combo.itemText(i).strip()
        ]
        if current and current not in options:
            options.append(current)

        name_item = self.table.item(row, 0)
        field_name = name_item.text() if name_item else ""
        dialog = OptionsDialog(self, field_name, options)
        if dialog.exec():
            new_options = dialog.options()
            combo.clear()
            combo.addItems(new_options)
            if current:
                combo.setCurrentText(current)

    def _read_states(self) -> list[FieldState]:
        """Collect the edited field states from the table."""
        states: list[FieldState] = []
        known = self.last_result.states if self.last_result else {}
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            if name_item is None:
                continue
            name = name_item.text().strip()
            base = known.get(name, FieldState(name=name))
            state = FieldState(
                name=name,
                value="",
                category=base.category or "personal",
                key=base.key or name,
                options=list(base.options),
                option_boxes=dict(base.option_boxes),
                mark="text",
                mark_kind=getattr(base, "mark_kind", "text") or "text",
                page=base.page,
                x=base.x,
                y=base.y,
                box=base.box,
                font_size=base.font_size,
                is_checkbox=base.is_checkbox,
            )

            editor = self.table.cellWidget(row, 1)
            if isinstance(editor, QComboBox):
                state.value = editor.currentText().strip()
                state.options = [
                    editor.itemText(i)
                    for i in range(editor.count())
                    if editor.itemText(i).strip()
                ]
                if state.value and state.value not in state.options:
                    state.options.append(state.value)  # newly added choice

            mark_widget = self.table.cellWidget(row, 2)
            if isinstance(mark_widget, QComboBox):
                state.mark = mark_widget.currentData() or "text"
            states.append(state)
        return states

    def _add_table_row(self, name: str, value: str, missing: bool = False):
        row = self.table.rowCount()
        self.table.insertRow(row)
        name_item = QTableWidgetItem(name)
        if missing:
            name_item.setForeground(Qt.red)
        self.table.setItem(row, 0, name_item)
        self.table.setItem(row, 1, QTableWidgetItem(value))
