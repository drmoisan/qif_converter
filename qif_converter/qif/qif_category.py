from __future__ import annotations

from dataclasses import dataclass
from ..qif import QifHeader, QifCode
from ..qif import qif_codes as codes
@dataclass
class QifCat:
    """
    Represents an account in QIF format.
    """
    name: str = ""
    description: str = ""

    @property
    def header(self) -> QifHeader:
        """
        Returns the type of the account.
        """
        h = QifHeader("!Type:Cat","Category list","Category")
        return h

    def emit_qif(self, with_header = False) -> str:
        if with_header:
            return f"{self.header.code}\nN{self.name}\nD{self.description}"
        return f"N{self.name}\nD{self.description}"

    def __eq__(self, other: object, /) -> bool:
        if not isinstance(other, QifCat):
            return False
        return (self.name == other.name
                and self.header == other.header)

    def __hash__(self) -> int:
        # Required if you want to use instances in sets/dicts and keep it consistent with __eq__
        return hash((self.name, self.header))