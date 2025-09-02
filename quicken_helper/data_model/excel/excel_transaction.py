# quicken_helper/data_model/excel/excel_transaction.py
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional
from quicken_helper.data_model.interfaces import ITransaction, EnumClearedStatus, ISplit

@dataclass(frozen=True)
class ExcelTransaction(ITransaction):
    """Adapter: an Excel group exposed as an ITransaction."""
    id: str
    date: date
    amount: Decimal
    payee: str = ""
    memo: str = ""
    category: str = ""
    cleared: EnumClearedStatus = field(default_factory=lambda: EnumClearedStatus.UNKNOWN)
    splits: Optional[List[ISplit]] = None
    action: Optional[str] = None  # for symmetry; probably None for Excel

    # Any normalization needed for matching should be done upstream or via helpers.
