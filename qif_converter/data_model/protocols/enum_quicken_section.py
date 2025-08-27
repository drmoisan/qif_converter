from enum import IntFlag, auto
from typing import Iterable


class QuickenSections(IntFlag):
    """
    Enum representing the sections of a QIF file.
    Each section is represented by a bit flag.
    """
    NONE = 0
    TAGS = auto()
    CATEGORIES = auto()
    ACCOUNTS = auto()
    TRANSACTIONS = auto()

    def has_flag(self, section: "QuickenSections") -> bool:
        """True if all bits in `section` are set on this mask."""
        return (self & section) == section

    def has_flags(self, sections: Iterable["QuickenSections"]) -> bool:
        """True if *all* flags in `sections` are set on this mask."""
        return all(self.has_flag(s) for s in sections)

    def add_flag(self, section: "QuickenSections") -> "QuickenSections":
        """Return a new mask with `section` added."""
        return self | section

    def add_flags(self, sections: Iterable["QuickenSections"]) -> "QuickenSections":
        """Return a new mask with *all* `sections` added."""
        mask = self
        for s in sections:
            mask |= s
        return mask

    def remove_flag(self, section: "QuickenSections") -> "QuickenSections":
        """Return a new mask with `section` cleared."""
        return self & ~section

    def remove_flags(self, sections: Iterable["QuickenSections"]) -> "QuickenSections":
        """Return a new mask with *all* `sections` cleared."""
        mask = self
        for s in sections:
            mask &= ~s
        return mask
