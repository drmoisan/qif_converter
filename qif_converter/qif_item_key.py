from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class QIFItemKey:
    """Uniquely identifies either a whole transaction or one of its splits."""
    txn_index: int             # index into original txns list
    split_index: Optional[int]  # None = whole transaction; otherwise 0..n-1

    def is_split(self) -> bool:
        return self.split_index is not None
