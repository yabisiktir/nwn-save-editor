"""What PRC has done to a character, read from its own ledger on the PC skin.

PRC templates do not apply hidden runtime effects. Their scripts call
``SetCompositeBonus(oSkin, "Template_Saint_con", 2, ITEM_PROPERTY_ABILITY_BONUS,
IP_CONST_ABILITY_CON)`` — they stamp **item properties onto the invisible skin**
the character wears. The contribution is therefore already in the save, and
anything that reads equipped item properties has already counted it.

Alongside those properties the skin keeps a named registry of every bonus:

    PRC_CBon_Names   = 24            how many
    PRC_CBon_Names_0 = Template_Saint_con
    Template_Saint_con = 2           the amount
    PRC_CBon_Exist_Template_Saint_con = 1

which is what makes the anonymous "+8 Constitution from a skin" legible as
"Saint +2, Half-troll +6". Reading it is presentation, not arithmetic: the
amounts are the same numbers, attributed. Adding both would double-count.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: ``Template_Saint_con`` -> source "Saint", ability field "Con".
_TEMPLATE = re.compile(r"^Template_(?P<source>.+?)_(?P<what>[a-zA-Z]+)$")

_ABILITY_SUFFIX = {
    "str": "Str", "dex": "Dex", "con": "Con",
    "int": "Int", "wis": "Wis", "cha": "Cha",
}


@dataclass(frozen=True)
class CompositeBonus:
    """One named entry in PRC's registry."""

    name: str
    value: int
    source: str = ""
    ability: str = ""

    @property
    def is_ability(self) -> bool:
        return bool(self.ability)


def read_registry(skin) -> list[CompositeBonus]:
    """Every composite bonus PRC records on the skin, in registry order.

    Falls back to reading whatever ``Template_*`` variables exist if the
    ``PRC_CBon_Names_*`` index is absent or inconsistent — the index is a
    convenience, not the storage.
    """
    variables = _variables(skin)
    if not variables:
        return []

    names: list[str] = []
    try:
        count = int(variables.get("PRC_CBon_Names") or 0)
    except (TypeError, ValueError):
        count = 0
    for i in range(count):
        name = variables.get(f"PRC_CBon_Names_{i}")
        if isinstance(name, str) and name:
            names.append(name)
    if not names:
        names = [k for k in variables if k.startswith("Template_")]

    out: list[CompositeBonus] = []
    for name in names:
        value = variables.get(name)
        if not isinstance(value, int):
            continue
        source, ability = _classify(name)
        out.append(CompositeBonus(name, value, source, ability))
    return out


def ability_sources(skin) -> dict[str, list[tuple[str, int]]]:
    """``{ability field: [(source, amount), …]}`` — who granted what, and how much.

    Only entries the registry names as an ability bonus are returned, so a
    caller can attribute a skin's ability properties without inventing any.
    """
    out: dict[str, list[tuple[str, int]]] = {}
    for bonus in read_registry(skin):
        if bonus.is_ability and bonus.value:
            out.setdefault(bonus.ability, []).append((bonus.source, bonus.value))
    return out


def template_names(skin) -> list[str]:
    """Templates applied to this character, in the order PRC registered them."""
    seen: list[str] = []
    for bonus in read_registry(skin):
        if bonus.source and bonus.source not in seen:
            seen.append(bonus.source)
    return seen


def _classify(name: str) -> tuple[str, str]:
    match = _TEMPLATE.match(name)
    if match is None:
        return "", ""
    source = match.group("source").replace("_", " ")
    return source, _ABILITY_SUFFIX.get(match.group("what").lower(), "")


def _variables(skin) -> dict[str, object]:
    field = getattr(skin, "fields", {}).get("VarTable") if skin is not None else None
    if field is None or not hasattr(field.value, "structs"):
        return {}
    out: dict[str, object] = {}
    for struct in field.value.structs:
        name = struct.get("Name")
        if name:
            out[str(name)] = struct.get("Value")
    return out
