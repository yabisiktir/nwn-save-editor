"""The Save Game Editor's section screens.

Each screen is a ``QWidget`` built against the small public surface on
:class:`~vaultkeeper.ui.save_editor.window.SaveEditorWindow` (``editing``,
``save``, ``session()``, ``rule_mode()``, ``character_info()``,
``notify_changed()``), and may expose a ``refresh()`` the shell calls when the
selection, the edit gate or the staged changes move.
"""

from __future__ import annotations
