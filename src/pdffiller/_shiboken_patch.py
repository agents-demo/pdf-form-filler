"""Workaround for an upstream incompatibility between PySide6 and openjiuwen.

PySide6 (via shiboken) installs an import hook
(``shibokensupport.signature.loader``) that inspects every newly imported
module with ``inspect.getsource`` to detect PySide usage. ``getsource``
unwraps the module by probing ``module.__wrapped__``. openjiuwen's lazy
packages (e.g. ``openjiuwen.core.foundation.store``) implement PEP 562
``__getattr__`` with an ``importlib.import_module("." + name)`` fallback, so
probing ``__wrapped__`` raises ``ModuleNotFoundError`` instead of
``AttributeError`` and crashes the import.

This module makes shiboken's inspector tolerate ``ImportError``. Returning
``False`` is the correct answer anyway: openjiuwen modules do not use PySide6.

Usage: call :func:`apply_workaround` once, after PySide6 has been imported and
before importing anything that pulls in openjiuwen.
"""
from __future__ import annotations

import sys

_MARKER = "_pdf_form_filler_safe"


def apply_workaround() -> bool:
    """Patch shiboken's module inspector to survive lazy PEP 562 modules.

    Returns:
        True if the workaround was applied or already active.
    """
    feature = sys.modules.get("shibokensupport.feature")
    if feature is None:
        return False
    original = getattr(feature, "_mod_uses_pyside", None)
    if original is None or getattr(original, _MARKER, False):
        return True

    def safe(module):
        try:
            return original(module)
        except ImportError:
            # Lazy PEP 562 modules raise ModuleNotFoundError for arbitrary
            # attribute probes (like inspect's '__wrapped__'). They do not
            # use PySide6, so "not a PySide module" is the correct answer.
            return False

    setattr(safe, _MARKER, True)
    feature._mod_uses_pyside = safe
    return True
