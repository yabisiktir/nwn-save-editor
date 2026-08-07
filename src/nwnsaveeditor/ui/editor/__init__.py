"""The Save Game Editor — the full-window editor.

It replaced an earlier tree-and-right-click dialog that grew editing onto a
read-only viewer. Two surfaces over one
:class:`~nwnsaveeditor.save_editor.SaveEditor` meant every fix needed doing twice,
and more than one of them was only ever done once — so there is deliberately just
this one now.
"""

from __future__ import annotations
