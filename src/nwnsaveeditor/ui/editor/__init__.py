"""The Save Game Editor — the full-window editor from ``docs/design_handoff_save_editor``.

The read-only :mod:`vaultkeeper.ui.dialogs.save_game_viewer` stays as it is; this
package is the designed editor that replaces it over time. Both drive the same
:class:`~nwnsaveeditor.save_editor.SaveEditor` session, so the write path,
verification and backup guarantees are unchanged.
"""

from __future__ import annotations
