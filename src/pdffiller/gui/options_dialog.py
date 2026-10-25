"""Dialog to change, add or delete a field's choice options."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)


class OptionsDialog(QDialog):
    """Manage the option list of one field: add / rename / delete."""

    def __init__(self, parent, field_name: str, options: list[str]):
        super().__init__(parent)
        self.setWindowTitle(f"Options for '{field_name}'")
        self.setMinimumSize(320, 320)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Choices for this field (pick one when filling):")
        )

        self.list = QListWidget()
        for option in options:
            self.list.addItem(option)
        layout.addWidget(self.list)

        buttons = QHBoxLayout()
        add_button = QPushButton("Add…")
        add_button.clicked.connect(self._add)
        edit_button = QPushButton("Rename…")
        edit_button.clicked.connect(self._rename)
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self._delete)
        for button in (add_button, edit_button, delete_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        close = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        close.accepted.connect(self.accept)
        close.rejected.connect(self.reject)
        layout.addWidget(close)

    def _add(self):
        text, ok = QInputDialog.getText(self, "Add option", "New option:")
        if ok and text.strip():
            self.list.addItem(text.strip())

    def _rename(self):
        row = self.list.currentRow()
        if row < 0:
            return
        text, ok = QInputDialog.getText(
            self, "Rename option", "Option:", text=self.list.item(row).text()
        )
        if ok and text.strip():
            self.list.item(row).setText(text.strip())

    def _delete(self):
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)

    def options(self) -> list[str]:
        return [self.list.item(i).text().strip() for i in range(self.list.count()) if self.list.item(i).text().strip()]
