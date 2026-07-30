"""The module's persistent variables — the save's world state.

A module keeps its script variables in ``module.ifo``'s ``VarTable``: the flags,
counters and strings a campaign uses to remember what has happened. On the owner's
save that is 821 entries, most of them PRC bookkeeping and quest progress.

Each entry carries its own ``Type`` code, and the code determines both what the
value means and which GFF type holds it. Only types that can be edited safely are
offered: an *object* variable stores an object id that is only meaningful to the
running game, so changing it by hand would point a script at the wrong thing.
"""

from __future__ import annotations

from dataclasses import dataclass

#: NWN's variable type codes, as they appear in a ``VarTable`` entry's ``Type``.
INT = 1
FLOAT = 2
STRING = 3
OBJECT = 4
LOCATION = 5

_TYPE_NAMES = {
    INT: "int",
    FLOAT: "float",
    STRING: "string",
    OBJECT: "object",
    LOCATION: "location",
}

#: Types a person can sensibly set. An object id and a location are runtime
#: handles — editing them by hand points scripts at something that is not there.
EDITABLE_TYPES = frozenset({INT, FLOAT, STRING})


@dataclass
class Variable:
    """One module variable."""

    index: int  #: position in the VarTable, which is how it is addressed
    name: str
    type_code: int
    value: object

    @property
    def type_name(self) -> str:
        return _TYPE_NAMES.get(self.type_code, f"type {self.type_code}")

    @property
    def editable(self) -> bool:
        return self.type_code in EDITABLE_TYPES

    @property
    def why_locked(self) -> str:
        """Why an uneditable variable is uneditable, in the user's terms."""
        if self.type_code == OBJECT:
            return "object ids only mean something to the running game"
        if self.type_code == LOCATION:
            return "locations are runtime handles"
        return "this variable's type is not understood"


def read_variables(tree) -> list[Variable]:
    """Every variable in a ``module.ifo`` tree, in table order."""
    entry = tree.root.fields.get("VarTable") if tree is not None else None
    table = entry.value if entry is not None else None  # .fields holds GffFields
    if table is None or not hasattr(table, "structs"):
        return []
    variables: list[Variable] = []
    for index, struct in enumerate(table.structs):
        name = struct.fields.get("Name")
        type_code = struct.fields.get("Type")
        value = struct.fields.get("Value")
        if name is None or type_code is None or value is None:
            continue
        variables.append(
            Variable(
                index=index,
                name=str(name.value),
                type_code=int(type_code.value),
                value=value.value,
            )
        )
    return variables


def matches(variable: Variable, needle: str) -> bool:
    """Whether ``variable`` should survive a search for ``needle``."""
    if not needle:
        return True
    needle = needle.lower()
    return needle in variable.name.lower() or needle in str(variable.value).lower()
