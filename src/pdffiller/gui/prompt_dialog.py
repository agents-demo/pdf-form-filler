"""Modal-style dialog that asks the user for a missing value."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ..controller import PromptRequest


class PromptDialog(QDialog):
    """Collect a value (and its data.md category/key) from the user."""

    submitted = Signal(str, str, str)  # value, category, key

    def __init__(self, parent, request: PromptRequest, categories: list[str]):
        super().__init__(parent)
        self.setWindowTitle("Missing information")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        question = request.question or f"What is the value for '{request.name}'?"
        label = QLabel(f"<b>{request.name}</b><br><br>{question}")
        label.setWordWrap(True)
        layout.addWidget(label)

        form = QFormLayout()
        if request.options:
            self.value_combo = QComboBox()
            self.value_combo.setEditable(True)
            self.value_combo.addItems(request.options)
            form.addRow("Value:", self.value_combo)
            self.value_edit = None
        else:
            self.value_edit = QLineEdit()
            self.value_edit.setPlaceholderText("Value")
            form.addRow("Value:", self.value_edit)

        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.addItems(sorted(set(categories)))
        if request.suggested_category:
            self.category_combo.setCurrentText(request.suggested_category)
        form.addRow("Category (data.md):", self.category_combo)

        self.key_edit = QLineEdit()
        if request.suggested_key:
            self.key_edit.setText(request.suggested_key)
        form.addRow("Key:", self.key_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self):
        if self.value_edit is not None:
            value = self.value_edit.text().strip()
            if not value:
                self.value_edit.setFocus()
                return
        else:
            value = self.value_combo.currentText().strip()
            if not value:
                self.value_combo.setFocus()
                return
        self.submitted.emit(
            value,
            self.category_combo.currentText().strip(),
            self.key_edit.text().strip(),
        )
        self.accept()
