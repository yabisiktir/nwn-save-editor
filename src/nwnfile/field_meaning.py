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
_GENDERS = ("Male", "Female", "Both", "Other", "None")
#: fields that are a row in a 2DA, resolved to that row's Label from the hak stack.
_LABELLED_2DA = {
    "Appearance_Type": ("appearance", "Appearance"),
    "SoundSetFile": ("soundset", "Sound set"),
    "Phenotype": ("phenotype", "Phenotype"),
    "CreatureSize": ("creaturesize", "Creature size"),
}


def _stack_label(stack, table: str, row_id: int) -> str | None:
    row = (stack.read_2da(table) or {}).get(row_id) if stack is not None else None
    if row is None:
        return None
    label = next((v for k, v in row.items() if k.lower() == "label"), None)
    return label.replace("_", " ") if label and label not in ("", "****") else None


def field_meaning(field_name: str, value, reference, stack=None) -> tuple[str, str] | None:
    """``(title, description)`` for an id-bearing raw field, or ``None``.

    ``reference`` is a ``CharacterReference`` (feat/spell names + descriptions);
    class and race names come from the ``nwnfile.character`` tables; ``stack`` (a
    hak stack, when available) resolves 2DA-backed fields like appearance and
    soundset against the character's own haks.
    """
    if not isinstance(value, int):
        return None
    if field_name in _LABELLED_2DA:
        table, noun = _LABELLED_2DA[field_name]
        label = _stack_label(stack, table, value)
        return (f"{noun} #{value}: {label}", "") if label else None
    if field_name == "Gender" and 0 <= value < len(_GENDERS):
        return f"Gender: {_GENDERS[value]}", ""
    if field_name == "GoodEvil":
        from nwnfile.character import _good_evil_word

        return f"Good–Evil {value}: {_good_evil_word(value)}", ""
    if field_name == "LawfulChaotic":
        from nwnfile.character import _lawful_chaotic_word

        return f"Law–Chaos {value}: {_lawful_chaotic_word(value)}", ""
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
    if field_name == "BaseItem":  # an item's type, from baseitems.2da
        from nwnfile.item_names import base_item_type

        name = base_item_type(value)
        return (f"Base item #{value}: {name}", "") if name else None
    return None
