"""What the save editor needs from whatever is hosting it.

The editor is a full window that Vaultkeeper opens, but it does not need
Vaultkeeper. Everything it asks of its host is here — four things, and it reads
all of them defensively, so a host that supplies none of them still opens (with
no game folder, the tables that need one simply report themselves unreadable).

Stating the surface as a protocol is what makes running the editor on its own
possible without a second implementation drifting from the first: Vaultkeeper's
own controller already satisfies it, and :class:`StandaloneHost` is the whole of
what a bare launcher has to provide.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from nwnsaveeditor.ui.editor.tokens import THEMES

#: Where a standalone run remembers its theme. Deliberately not Vaultkeeper's
#: settings file — running the editor on its own must not write to the app's
#: configuration, which the app may have open at the same time.
STANDALONE_SETTINGS = "save_editor.json"


@runtime_checkable
class EditorContext(Protocol):
    """Where the game is. Both may be ``None``; the editor copes."""

    game_root: Path | None
    game_user_dir: Path | None


@runtime_checkable
class EditorHost(Protocol):
    """The whole of the editor's dependency on its host application."""

    ctx: EditorContext

    def _settings(self):
        """An object carrying ``save_editor_theme``."""

    def set_save_editor_theme(self, name: str) -> None:
        """Remember the chosen theme."""


class _Context:
    def __init__(self, game_root: Path | None, game_user_dir: Path | None) -> None:
        self.game_root = game_root
        self.game_user_dir = game_user_dir


class _Settings:
    def __init__(self, save_editor_theme: str) -> None:
        self.save_editor_theme = save_editor_theme


class StandaloneHost:
    """A host for running the editor with no Vaultkeeper application.

    Finds the game the same way the app does when it can, falls back to the
    platform's usual locations, and keeps its own tiny settings file.
    """

    def __init__(
        self,
        game_root: Path | None = None,
        game_user_dir: Path | None = None,
        settings_dir: Path | None = None,
    ) -> None:
        self.ctx = _Context(
            game_root if game_root is not None else default_game_root(),
            game_user_dir if game_user_dir is not None else default_user_dir(),
        )
        self._settings_path = (
            (settings_dir or default_settings_dir()) / STANDALONE_SETTINGS
        )
        self._theme = self._read_theme()

    # -- the protocol ------------------------------------------------------- #
    def _settings(self) -> _Settings:
        return _Settings(self._theme)

    def set_save_editor_theme(self, name: str) -> None:
        if name not in THEMES:
            return
        self._theme = name
        try:
            self._settings_path.parent.mkdir(parents=True, exist_ok=True)
            self._settings_path.write_text(
                json.dumps({"save_editor_theme": name}, indent=2), encoding="utf-8"
            )
        except OSError:
            pass  # a theme that cannot be remembered is not worth failing over

    # -- persistence -------------------------------------------------------- #
    def _read_theme(self) -> str:
        try:
            data = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "dark"
        theme = data.get("save_editor_theme")
        return theme if theme in THEMES else "dark"


def default_user_dir() -> Path | None:
    """The NWN user directory — where saves, haks and portraits live on EE."""
    candidates = [
        Path.home() / "Documents" / "Neverwinter Nights",
        Path.home() / "Documents" / "Neverwinter Nights 2",
    ]
    return next((path for path in candidates if path.is_dir()), None)


def default_game_root() -> Path | None:
    """The installed game, looked for where the usual stores put it."""
    home = Path.home()
    candidates = [
        home / "Library/Application Support/Steam/steamapps/common/Neverwinter Nights",
        Path("/Applications/Neverwinter Nights Enhanced Edition"),
        home / ".steam/steam/steamapps/common/Neverwinter Nights",
        home / ".local/share/Steam/steamapps/common/Neverwinter Nights",
        Path("C:/Program Files (x86)/Steam/steamapps/common/Neverwinter Nights"),
        Path("C:/Program Files/Steam/steamapps/common/Neverwinter Nights"),
    ]
    return next((path for path in candidates if path.is_dir()), None)


def default_settings_dir() -> Path:
    """Where a standalone run keeps its own settings, per platform convention."""
    import sys

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "vaultkeeper"
    if sys.platform.startswith("win"):
        import os

        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "vaultkeeper"
    return Path.home() / ".config" / "vaultkeeper"
