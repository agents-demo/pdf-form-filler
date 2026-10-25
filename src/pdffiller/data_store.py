"""Read and update the hierarchical ``data.json`` file.

Format::

    {
      "language": "en",
      "personal": {
        "First name": "Yoni",
        "Gender": {"value": "Male", "options": ["Male", "Female", "Other"]}
      }
    }

Top-level keys are categories ("sections"). Reserved heading ``language``
selects the fill language. A field entry is either a plain string (the value)
or an object with ``value`` and ``options`` (choice list).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

_NORM_RE = re.compile(r"[_\-\s]+")


def _norm_key(key: str) -> str:
    """Normalize a field key for matching: spaces == underscores == hyphens."""
    return _NORM_RE.sub(" ", str(key).strip()).lower()


class DataStore:
    """Parse, query and update the hierarchical JSON data file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data: dict[str, Any] = {}
        self._loaded = False

    # -- loading ----------------------------------------------------------
    def load(self) -> "DataStore":
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}
        else:
            self._data = {}
        if not isinstance(self._data, dict):
            self._data = {}
        self._data.setdefault("language", "en")
        self._loaded = True
        return self

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    # -- queries ----------------------------------------------------------
    @property
    def language(self) -> str:
        return str(self._data.get("language", "en") or "en")

    def set_language(self, language: str) -> None:
        self._data["language"] = language.strip() or "en"

    def section_titles(self) -> list[str]:
        return [k for k in self._data if k != "language"]

    def _categories(self, section_title: Optional[str]) -> list[dict]:
        if section_title:
            section = self._data.get(section_title)
            return [section] if isinstance(section, dict) else []
        return [
            v for k, v in self._data.items() if k != "language" and isinstance(v, dict)
        ]

    @staticmethod
    def _field_entry(category: dict, key: str):
        target = _norm_key(key)
        for k, v in category.items():
            if _norm_key(k) == target:
                return k, v
        return None, None

    def get(self, key: str, section_title: Optional[str] = None) -> Optional[str]:
        for category in self._categories(section_title):
            _, entry = self._field_entry(category, key)
            if entry is None:
                continue
            if isinstance(entry, str):
                return entry
            if isinstance(entry, dict):
                return str(entry.get("value", ""))
        return None

    def get_options(self, key: str, section_title: Optional[str] = None) -> list[str]:
        for category in self._categories(section_title):
            _, entry = self._field_entry(category, key)
            if isinstance(entry, dict):
                options = entry.get("options") or []
                return [str(o) for o in options]
        return []

    def items(self, section_title: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for category in self._categories(section_title):
            for key, entry in category.items():
                if isinstance(entry, str):
                    result[key] = entry
                elif isinstance(entry, dict):
                    result[key] = str(entry.get("value", ""))
        return result

    def as_flat(self) -> dict[str, str]:
        flat: dict[str, str] = {}
        for category_name, category in self._data.items():
            if category_name == "language" or not isinstance(category, dict):
                continue
            for key, entry in category.items():
                value = entry if isinstance(entry, str) else str(entry.get("value", ""))
                flat[f"{category_name}/{key}"] = value
                if key not in flat:
                    flat[key] = value
        return flat

    # -- mutation ---------------------------------------------------------
    def upsert(
        self,
        category: str,
        key: str,
        value: str,
        options: Optional[list[str]] = None,
    ) -> None:
        """Insert or update ``key`` in ``category``, creating it if needed."""
        section = self._data.setdefault(category, {})
        if not isinstance(section, dict):
            section = self._data[category] = {}

        existing_key, _ = self._field_entry(section, key)
        target_key = existing_key or key

        if options:
            section[target_key] = {
                "value": value,
                "options": [o.strip() for o in options if o.strip()],
            }
        else:
            section[target_key] = value

    def to_text(self) -> str:
        """Return the current file contents as JSON text."""
        return json.dumps(self._data, indent=2, ensure_ascii=False)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data.setdefault("language", "en")
        self._loaded = True
        self.path.write_text(self.to_text() + "\n", encoding="utf-8")

