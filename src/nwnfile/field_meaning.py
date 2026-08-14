"""What a raw GFF scalar *means* — resolving id fields to names and descriptions.

The Raw Data tree shows a field like ``Feat = 2213`` or ``Class = 27`` as a bare
number; this turns the ones that are ids into something readable, so the editor
can say what the value refers to without leaving the tree. Only fields whose value
is genuinely an id of a known kind resolve; everything else returns ``None`` and
the UI shows nothing extra.
"""

from __future__ import annotations

_ABILITIES = (
    "Strength", "Dexterity", "Constitution", "Intelligence", "Wisdom", "Charisma",
)


def field_meaning(field_name: str, value, reference) -> tuple[str, str] | None:
    """``(title, description)`` for an id-bearing raw field, or ``None``.

    ``reference`` is a ``CharacterReference`` (feat/spell names + descriptions);
    class and race names come from the ``nwnfile.character`` tables.
    """
    if not isinstance(value, int):
        return None
    if field_name == "Feat":
        return f"Feat #{value}: {reference.feat_name(value)}", reference.feat_description(value)
    if field_name == "Spell":
        return f"Spell #{value}: {reference.spell_name(value)}", reference.spell_description(value)
    if field_name in ("Class", "LvlStatClass"):
        from nwnfile.character import class_name

        return f"Class #{value}: {class_name(value)}", ""
    if field_name in ("Race", "Subrace"):
        from nwnfile.character import race_name

        return f"Race #{value}: {race_name(value)}", ""
    if field_name == "LvlStatAbility" and 0 <= value < len(_ABILITIES):
        return f"Ability raised at this level: {_ABILITIES[value]}", ""
    if field_name == "Skill":  # some lists store a skill id directly
        return f"Skill #{value}: {reference.skill_name(value)}", ""
    return None
