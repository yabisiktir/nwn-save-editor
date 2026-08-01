"""Logging for the format readers, with no application attached.

The readers want to say when a file is malformed, and nothing more. Naming their
logger here rather than importing an application's keeps this package free of any
particular app's paths and configuration — a host that wants these lines in its
own log attaches a handler to the ``nwnfile`` logger.
"""

from __future__ import annotations

import logging

LOG_NAME = "nwnfile"


def get_logger(name: str | None = None) -> logging.Logger:
    """A child of this package's logger (e.g. ``get_logger(__name__)``)."""
    if name is None or name == LOG_NAME:
        return logging.getLogger(LOG_NAME)
    return logging.getLogger(LOG_NAME).getChild(name)
