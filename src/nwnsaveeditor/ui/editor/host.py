"""What the save editor needs from whatever is hosting it.

The editor is a full window an application can open, but it does not need one.
Everything it *requires* of a host is here — four things, read defensively, so a
host that supplies none of them still opens (with no game folder, the tables that
need one simply report themselves unreadable).

A host may also offer ``portrait_path(resref, extra_dirs=...)``. That one is
optional and is used when present, because an application may know about
portraits the editor cannot find on its own — ones its mod installs put down, or
ones extracted out of haks. Without it the editor searches NWN's own portrait
folders, which is enough to show the portrait of a normal character.

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

#: Where a standalone run remembers its theme. Its own file under its own
#: directory: a host that embeds the editor supplies its settings instead, and a
#: standalone run must never write into the embedding application's config.
STANDALONE_SETTINGS = "save_editor.json"

#: What the title bar says when nothing tells it otherwise.
#:
#: A host that embeds the editor puts its own name here, because to the person
#: using it the editor is part of that application. Running on its own it is not
#: part of anything, and said "VAULTKEEPER" for a while — an application the user
#: may not have installed.
DEFAULT_WORDMARK = "NWN SAVE EDITOR"


@runtime_checkable
class EditorContext(Protocol):
    """Where the game is. Both may be ``None``; the editor copes."""

    game_root: Path | None
    game_user_dir: Path | None


@runtime_checkable
class EditorHost(Protocol):
    """What the editor requires of its host. See also the optional lookup above.

    A host may also carry a ``wordmark`` — the name shown in the title bar. It is
    optional, like ``portrait_path`` and ``set_game_paths``: without one the
    editor uses :data:`DEFAULT_WORDMARK` and calls itself what it is.
    """

    ctx: EditorContext

    def _settings(self):
        """An object carrying ``save_editor_theme``."""

    def set_save_editor_theme(self, name: str) -> None:
        """Remember the chosen theme."""


def wordmark_for(controller) -> str:
    """The name to show for whoever is hosting the editor."""
    name = getattr(controller, "wordmark", "") if controller is not None else ""
    return str(name).strip() or DEFAULT_WORDMARK


class _Context:
    def __init__(self, game_root: Path | None, game_user_dir: Path | None) -> None:
        self.game_root = game_root
        self.game_user_dir = game_user_dir


class _Settings:
    def __init__(self, save_editor_theme: str) -> None:
        self.save_editor_theme = save_editor_theme


class StandaloneHost:
    """A host for running the editor with no application around it.

    Where the game is gets settled once, in this order: what the caller passed,
    then what was saved last time, then detection. Whatever it lands on is
    written back, so a machine where detection guesses wrong — or where the game
    is somewhere unusual — is a one-time ``--game-root`` away from working, not a
    flag on every launch.
    """

    def __init__(
        self,
        game_root: Path | None = None,
        game_user_dir: Path | None = None,
        settings_dir: Path | None = None,
    ) -> None:
        self._settings_path = (
            (settings_dir or default_settings_dir()) / STANDALONE_SETTINGS
        )
        saved = self._read()
        self._theme = saved.get("save_editor_theme", "dark")
        if self._theme not in THEMES:
            self._theme = "dark"

        root = game_root or _saved_dir(saved, "game_root") or default_game_root()
        user = game_user_dir or _saved_dir(saved, "game_user_dir") or default_user_dir()
        self.ctx = _Context(root, user)
        self.remember_paths()

    # -- the protocol ------------------------------------------------------- #
    def _settings(self) -> _Settings:
        return _Settings(self._theme)

    def set_save_editor_theme(self, name: str) -> None:
        if name not in THEMES:
            return
        self._theme = name
        self._write()

    def set_game_paths(
        self, game_root: Path | None = None, game_user_dir: Path | None = None
    ) -> None:
        """Point the editor at a different game folder, and remember it.

        Its presence is what tells the settings screen the paths are the
        editor's to change. A host that owns them — an application with its own
        game-folder setting — simply does not offer this, and the screen shows
        them read-only rather than writing somewhere with no effect.
        """
        if game_root is not None:
            self.ctx.game_root = game_root
        if game_user_dir is not None:
            self.ctx.game_user_dir = game_user_dir
        self._write()

    # -- persistence -------------------------------------------------------- #
    def remember_paths(self) -> None:
        """Write the folders currently in use, so the next run starts there."""
        self._write()

    def _read(self) -> dict:
        try:
            data = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self) -> None:
        payload = {"save_editor_theme": self._theme}
        for key, value in (("game_root", self.ctx.game_root),
                           ("game_user_dir", self.ctx.game_user_dir)):
            if value is not None:
                payload[key] = str(value)
        try:
            self._settings_path.parent.mkdir(parents=True, exist_ok=True)
            self._settings_path.write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
        except OSError:
            pass  # settings that cannot be remembered are not worth failing over


def _saved_dir(saved: dict, key: str) -> Path | None:
    """A remembered folder, if it is still there.

    A path that has gone — an unplugged drive, an uninstalled game — falls
    through to detection rather than pinning the editor to somewhere empty.
    """
    value = saved.get(key)
    if not value:
        return None
    path = Path(value)
    return path if path.is_dir() else None


def default_user_dir() -> Path | None:
    """The NWN user directory — where saves, haks and portraits live on EE.

    Per platform, because it is not the same place: macOS and Windows use
    ``Documents/Neverwinter Nights``, but Enhanced Edition on Linux uses
    ``~/.local/share/Neverwinter Nights``. Guessing Documents everywhere finds
    nothing on a Linux machine.
    """
    from nwnfile.locations import HostOS, user_documents_dir

    path = user_documents_dir(HostOS.current())
    return path if path.is_dir() else None


def default_game_root() -> Path | None:
    """The installed game, wherever this platform's stores put it.

    Delegated rather than guessed at: :mod:`nwnfile.locations` walks Steam's
    library folders (which are not always the default one), GOG and Beamdog
    installs, and Wine/CrossOver prefixes, and checks each candidate actually
    looks like an NWN root instead of trusting the path.
    """
    from nwnfile.locations import discover_installs

    found = discover_installs()
    return found[0].root if found else None


def default_settings_dir() -> Path:
    """Where a standalone run keeps its own settings, per platform convention."""
    import sys

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "nwn-save-editor"
    if sys.platform.startswith("win"):
        import os

        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "nwn-save-editor"
    return Path.home() / ".config" / "nwn-save-editor"
