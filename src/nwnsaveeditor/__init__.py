"""Read and edit Neverwinter Nights save games.

A ``.sav`` is an ERF holding the module's state — ``module.ifo`` with the player
character inside it, and one ``.git``/``.are`` pair per area. This package
decodes all of that, stages edits against it, and writes a verified new save.
The editor window in :mod:`nwnsaveeditor.ui.editor` is a view over it.

Built on :mod:`nwnfile` for the formats and the tables that name their contents.
It does not know about Vaultkeeper; Vaultkeeper opens it, which is the only
direction that arrow points.
"""
