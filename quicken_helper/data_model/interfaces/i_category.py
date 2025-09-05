from __future__ import annotations

from typing import Protocol, runtime_checkable

from .i_comparable import IComparable
from .i_equatable import IEquatable
from .i_has_emit_qif import HasEmitQifWithHeader
from .i_to_dict import IToDict


@runtime_checkable
class ICategory(HasEmitQifWithHeader, Protocol, IComparable, IEquatable, IToDict):
    """
    Protocol for QIF Category list entries (i.e., records in !Type:Cat).

    A conforming object should expose at least:
      - name: category name (e.g., "Food:Groceries")
      - description: human-readable description (may be empty)
      - is_income: True if this is an income category (QIF 'I'), else False (expense; QIF 'E')
      - is_expense: convenience inverse of is_income
      - tax_related: whether the category is tax-related (if tracked)
      - tax_schedule: optional tax schedule code / label (may be empty)

    It must also be able to emit itself as QIF via `emit_qif`.
    """

    # --- core identity/metadata ---
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    # --- type flags ---
    @property
    def is_income(self) -> bool: ...

    @property
    def is_expense(self) -> bool: ...

    # --- tax metadata (optional but commonly present) ---
    @property
    def tax_related(self) -> bool: ...

    @property
    def tax_schedule(self) -> str: ...

    # # --- data_model emission (inherited from HasEmitQif) ---
    # def emit_qif(self, out: TextIO) -> None: ...
