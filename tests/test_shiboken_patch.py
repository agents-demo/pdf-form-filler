"""Tests for the shiboken (PySide6) import-hook workaround."""
import sys
import types

import pytest

from pdffiller._shiboken_patch import apply_workaround


@pytest.fixture
def fake_feature_module(monkeypatch):
    """Install a stub ``shibokensupport.feature`` in sys.modules."""
    module = types.ModuleType("shibokensupport.feature")

    def _mod_uses_pyside(mod):
        # Simulate shiboken probing a lazy PEP 562 module: the probe of
        # ``mod.__wrapped__`` surfaces as an ImportError.
        raise ModuleNotFoundError(f"No module named '{mod.__name__}.__wrapped__'")

    module._mod_uses_pyside = _mod_uses_pyside
    monkeypatch.setitem(sys.modules, "shibokensupport.feature", module)
    return module


def test_apply_workaround_survives_import_errors(fake_feature_module):
    assert apply_workaround() is True
    # The patched inspector must swallow ImportError and return False.
    lazy = types.ModuleType("openjiuwen.core.foundation.store")
    assert fake_feature_module._mod_uses_pyside(lazy) is False


def test_apply_workaround_idempotent(fake_feature_module):
    apply_workaround()
    patched = fake_feature_module._mod_uses_pyside
    apply_workaround()
    assert fake_feature_module._mod_uses_pyside is patched


def test_apply_workaround_noop_without_module(monkeypatch):
    monkeypatch.delitem(sys.modules, "shibokensupport.feature", raising=False)
    assert apply_workaround() is False
