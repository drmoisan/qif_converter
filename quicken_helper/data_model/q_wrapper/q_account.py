from __future__ import annotations

from dataclasses import dataclass

from .qif_header import QifHeader


@dataclass
class QAccount:
    """
    Represents an account in QIF format.
    """

    name: str = ""
    type: str = ""
    description: str = ""

    @property
    def header(self) -> QifHeader:
        """
        Returns the type of the account.
        """
        h = QifHeader("!Account", "Account list or which account follows", "Account")
        return h

    def qif_entry(self, with_header=False) -> str:
        if with_header:
            return f"{self.header.code}\nN{self.name}\nT{self.type}\nD{self.description}\n^"
        return f"N{self.name}\nT{self.type}\nD{self.description}\n^"

    def __eq__(self, other: object, /) -> bool:
        if not isinstance(other, QAccount):
            return False
        return (
            self.name == other.name
            and self.type == other.type
            and self.header == other.header
        )

    def __hash__(self) -> int:
        # Required if you want to use instances in sets/dicts and keep it consistent with __eq__
        return hash((self.name, self.type, self.header))
