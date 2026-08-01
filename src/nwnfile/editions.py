"""NWN edition identity.

The original tool (Defs.Enums.Edition) distinguishes the classic 2002 game
("Diamond") from the 2018 Beamdog remaster ("Enhanced Edition"/EE). Almost all
modern installs — and every native macOS/Linux install — are EE; Diamond is
effectively Windows/Wine-only. Vaultkeeper keeps the distinction because it
changes the legal game-folder layout, launch strategy, and Steam Workshop
availability, but treats EE as the default.
"""

from __future__ import annotations

from enum import StrEnum


class Edition(StrEnum):
    """Which NWN release a game folder / profile targets."""

    ENHANCED = "enhanced"  # Neverwinter Nights: Enhanced Edition (Beamdog, 2018)
    DIAMOND = "diamond"    # Neverwinter Nights Diamond (BioWare/Atari, 2002)

    @property
    def display_name(self) -> str:
        return {
            Edition.ENHANCED: "Enhanced Edition",
            Edition.DIAMOND: "Diamond",
        }[self]

    @property
    def steam_app_id(self) -> str | None:
        """Steam application id, if this edition ships on Steam."""
        return "704450" if self is Edition.ENHANCED else None

    @property
    def steam_workshop_id(self) -> str | None:
        """Steam Workshop content id (same as the app id for EE)."""
        return "704450" if self is Edition.ENHANCED else None
