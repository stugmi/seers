"""The 13 debug-name tables in archive 24 of the game cache."""

from __future__ import annotations

from seers._compat import StrEnum


class Kind(StrEnum):
    """A debug-name table: its attribute name (the value), cache table name and JS5 group.

    >>> Kind.ITEMS.table, Kind.ITEMS.group
    ('objtypes', 0)
    >>> Kind("items") is Kind.ITEMS
    True
    """

    table: str
    group: int

    def __new__(cls, alias: str, table: str, group: int) -> Kind:
        member = str.__new__(cls, alias)
        member._value_ = alias
        member.table = table
        member.group = group
        return member

    VARPS = ("varps", "varptypes", 3)
    VARBITS = ("varbits", "varbittypes", 4)
    INTERFACES = ("interfaces", "iftypes", 14)
    INVENTORIES = ("inventories", "invtypes", 2)
    LOCS = ("locs", "loctypes", 6)
    NPCS = ("npcs", "npctypes", 1)
    ITEMS = ("items", "objtypes", 0)
    DBROWS = ("dbrows", "rowtypes", 9)
    ANIMATIONS = ("animations", "seqtypes", 7)
    SOUNDS = ("sounds", "soundtypes", 11)
    SPOTANIMS = ("spotanims", "spottypes", 8)
    SPRITES = ("sprites", "spritetypes", 12)
    DBTABLES = ("dbtables", "tabletypes", 10)

    @property
    def composite(self) -> bool:
        """IDs are ``id:component`` (interfaces) or ``id:column`` (DB tables)."""
        return self in (Kind.INTERFACES, Kind.DBTABLES)
