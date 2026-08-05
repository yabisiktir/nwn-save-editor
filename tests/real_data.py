"""Where the optional real-data tests look for real data.

A few tests check the readers against genuine game files rather than fixtures — a
real CEP hak says things a synthetic one cannot, like that the resource count and
the type→extension mapping hold on a file somebody actually shipped.

**Nothing depends on any of it.** The path is opt-in through an environment
variable and every test using it skips when that is unset or missing, so the
suite is complete and green on a machine that has none of it — which is every CI
runner, and anyone who is not the author.

This used to be a hardcoded absolute path under one person's home directory,
which put their private folder layout in a public repository.

To run them, point at your own:

    export NWN_TEST_NIT_STORE="$HOME/Documents/NIT Store"
"""

from __future__ import annotations

import os
from pathlib import Path

#: The environment variable naming the optional folder.
NIT_STORE_VAR = "NWN_TEST_NIT_STORE"


def nit_store() -> Path | None:
    """A legacy NIT Store to read real haks from, or ``None``."""
    value = os.environ.get(NIT_STORE_VAR, "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_dir() else None


#: Said once, so every skip reads the same and explains how to opt in.
REASON = f"needs real game files; set {NIT_STORE_VAR} to run it (see tests/real_data.py)"
