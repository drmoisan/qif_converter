from __future__ import annotations

from dataclasses import dataclass

from ..data_model.protocols import ITag, IHeader
from ..data_model import QifHeader

@dataclass
class QTag(ITag):
    """
    Represents an account in QIF format.
    """
    name: str = ""
    description: str = ""

    @property
    def header(self) -> IHeader:
        """
        Returns the type of the account.
        """
        h = QifHeader("!Type:Tag","Tag list","Tag")
        return h

    def emit_qif(self, with_header = False) -> str:
        if with_header:
            return f"{self.header.code}\nN{self.name}\nD{self.description}\n^"
        return f"N{self.name}\nD{self.description}"

    def __eq__(self, other: object, /) -> bool:
        if not isinstance(other, ITag):
            return False
        return (self.name == other.name
                and self.header == other.header)

    def __hash__(self) -> int:
        # Required if you want to use instances in sets/dicts and keep it consistent with __eq__
        return hash((self.name, self.header))