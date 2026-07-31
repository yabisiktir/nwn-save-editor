"""The natural weapons PRC records for a character — claws, bites and the rest.

A creature's claw or bite is an ordinary item worn in one of the three creature
weapon slots, so the *equipped* ones already show up as equipment. But PRC does
not leave them equipped: it keeps the character's full set in the character's own
``VarTable`` and swaps them into those slots at runtime, by script.

The entries look like this — ``ARRAY_`` names are PRC's array convention, the
number being the index::

    ARRAY_NAT_PRI_WEAP_RESREF_0 = prc_claw_1d6l_m     # primary
    ARRAY_NAT_SEC_WEAP_RESREF_0 = prc_rdd_bite_m      # secondary
    ARRAY_NAT_SEC_WEAP_RESREF_1 = prc_raks_bite_m

So a Red Dragon Disciple's bite can be entirely absent from the equipment slots
and still be part of the character. Reading it here is what makes the difference
between "the editor lost my bite attack" and "PRC has it, it is just not the
weapon currently in hand".

This is a *read*: the set is derived from the character's classes and feats by
PRC's own scripts, so editing the list would be overwritten at the next
recalculation.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The VarTable name prefixes PRC uses, and what that group means.
PRIMARY_PREFIX = "ARRAY_NAT_PRI_WEAP_RESREF_"
SECONDARY_PREFIX = "ARRAY_NAT_SEC_WEAP_RESREF_"

#: Equip slot bits that hold a creature weapon.
CREATURE_WEAPON_SLOTS: tuple[int, ...] = (16384, 32768, 65536)


@dataclass(frozen=True)
class NaturalWeapon:
    """One natural weapon PRC has recorded for the character."""

    resref: str
    group: str  #: "primary" | "secondary"
    index: int  #: its position in PRC's array
    equipped_slot: int | None = None  #: the creature slot holding it, if any

    @property
    def equipped(self) -> bool:
        return self.equipped_slot is not None

    @property
    def label(self) -> str:
        """A readable name from the blueprint resref, which is all the save has.

        ``prc_rdd_bite_m`` is the Red Dragon Disciple's medium bite; there is no
        localized name to look up, because the blueprint lives in a hak the save
        does not carry. Tidying the resref is honest and beats showing nothing.
        """
        parts = [p for p in self.resref.split("_") if p and p != "prc"]
        if parts and parts[-1] in _SIZES:
            parts = parts[:-1] + [f"({_SIZES[parts[-1]]})"]
        return " ".join(parts) or self.resref


#: The size suffix PRC puts on a natural weapon blueprint.
_SIZES = {
    "t": "tiny", "s": "small", "m": "medium", "l": "large", "h": "huge",
}


def natural_weapons(variables, equipped_resrefs=None) -> list[NaturalWeapon]:
    """PRC's recorded natural weapons, marked with whether each is equipped.

    ``variables`` is the character's ``VarTable`` as ``(name, value)`` pairs;
    ``equipped_resrefs`` maps a lowercased resref to the creature slot holding it.
    """
    equipped_resrefs = {k.lower(): v for k, v in (equipped_resrefs or {}).items()}
    found: list[NaturalWeapon] = []
    for name, value in variables:
        for prefix, group in ((PRIMARY_PREFIX, "primary"), (SECONDARY_PREFIX, "secondary")):
            if not str(name).startswith(prefix):
                continue
            resref = str(value or "").strip()
            if not resref:
                continue
            try:
                index = int(str(name)[len(prefix):])
            except ValueError:
                continue
            found.append(NaturalWeapon(
                resref=resref, group=group, index=index,
                equipped_slot=equipped_resrefs.get(resref.lower()),
            ))
    # Primaries first, then by PRC's own array order — the order the scripts use.
    found.sort(key=lambda weapon: (weapon.group != "primary", weapon.index))
    return found
