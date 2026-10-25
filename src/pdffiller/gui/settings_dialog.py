"""Settings dialog for LLM configuration."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from ..config import LLMConfig


class SettingsDialog(QDialog):
    def __init__(self, parent, config: LLMConfig):
        super().__init__(parent)
        self.setWindowTitle("LLM Settings")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.api_key = QLineEdit(config.api_key)
        self.api_key.setEchoMode(QLineEdit.Password)
        form.addRow("API key:", self.api_key)

        self.api_base = QLineEdit(config.api_base)
        form.addRow("API base URL:", self.api_base)

        self.provider = QLineEdit(config.provider)
        form.addRow("Provider:", self.provider)

        self.model = QLineEdit(config.model)
        form.addRow("Model:", self.model)

        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.1)
        self.temperature.setValue(config.temperature)
        form.addRow("Temperature:", self.temperature)

        self.max_tokens = QSpinBox()
        self.max_tokens.setRange(256, 65536)
        self.max_tokens.setValue(config.max_tokens)
        form.addRow("Max tokens:", self.max_tokens)

        self.timeout = QSpinBox()
        self.timeout.setRange(10, 3600)
        self.timeout.setSuffix(" s")
        self.timeout.setValue(int(config.timeout))
        form.addRow("Request timeout:", self.timeout)

        self.verify_ssl = QCheckBox("Verify SSL")
        self.verify_ssl.setChecked(config.verify_ssl)
        form.addRow("", self.verify_ssl)

        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def config(self) -> LLMConfig:
        return LLMConfig(
            provider=self.provider.text().strip() or "DeepSeek",
            api_base=self.api_base.text().strip(),
            api_key=self.api_key.text().strip(),
            model=self.model.text().strip(),
            temperature=self.temperature.value(),
            max_tokens=self.max_tokens.value(),
            timeout=float(self.timeout.value()),
            verify_ssl=self.verify_ssl.isChecked(),
        )
