"""Entry point: run the PDF form filler GUI.

Usage:
    uv run python -m pdffiller
"""
from __future__ import annotations

import asyncio
import sys


def main() -> int:
    from .config import ensure_direct_connection
    from .logging_setup import setup_logging

    setup_logging()
    # All LLM requests connect directly; never through a proxy.
    ensure_direct_connection()
    log_startup_info()

    import qasync
    from PySide6.QtWidgets import QApplication

    from ._shiboken_patch import apply_workaround

    # PySide6 (shiboken) inspects every imported module with
    # ``inspect.getsource``; openjiuwen's lazy PEP 562 modules crash that
    # probe. Apply the workaround before anything imports openjiuwen.
    apply_workaround()

    from .gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("PDF Form Filler")
    install_excepthook()

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow(loop)
    window.show()

    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)

    with loop:
        loop.run_until_complete(app_close_event.wait())

    return 0


def install_excepthook() -> None:
    """Log and report unhandled exceptions instead of crashing the app."""
    import logging
    import traceback

    from PySide6.QtWidgets import QMessageBox

    log = logging.getLogger(__name__)

    def hook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log.error("Unhandled exception:\n%s", text)
        try:
            QMessageBox.critical(
                None,
                "Unexpected error",
                f"An unexpected error occurred:\n\n{exc_value}\n\n"
                f"See logs/pdffiller.log for details.",
            )
        except Exception:  # noqa: BLE001 - never mask the original error
            pass

    sys.excepthook = hook


def log_startup_info() -> None:
    import logging
    import platform
    import socket
    from urllib.parse import urlparse

    from .config import LLMConfig
    from .logging_setup import mask_key

    log = logging.getLogger(__name__)
    cfg = LLMConfig.from_env()
    log.info(
        "Startup: python=%s platform=%s provider=%s model=%s base=%s key=%s "
        "verify_ssl=%s timeout=%ss",
        platform.python_version(),
        platform.platform(),
        cfg.provider,
        cfg.model,
        cfg.api_base,
        mask_key(cfg.api_key),
        cfg.verify_ssl,
        cfg.timeout,
    )
    # Diagnostic: does the API host resolve right now?
    try:
        host = urlparse(cfg.api_base).hostname or ""
        ip = socket.gethostbyname(host) if host else ""
        log.info("DNS check: %s -> %s", host, ip or "<unresolved>")
    except Exception as exc:  # noqa: BLE001
        log.warning("DNS check failed for %s: %s", cfg.api_base, exc)


if __name__ == "__main__":
    raise SystemExit(main())
