from __future__ import annotations

import logging


def configure_logging(*, debug: bool) -> None:
    """Configure package-wide logging.

    This is intentionally lightweight and safe to call multiple times.
    """

    level = logging.DEBUG if debug else logging.WARNING
    root = logging.getLogger()

    # Avoid duplicate handlers if configure_logging is called more than once.
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)

    root.setLevel(level)
