# quicken_helper/controllers/data_session.py
from __future__ import annotations

import logging
import logging.config
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from quicken_helper.controllers import match_excel as mex
from quicken_helper.controllers.qif_loader import load_transactions_protocol
from quicken_helper.data_model.excel import (
    ExcelTransaction,
    ExcelTxnGroup,
    map_group_to_excel_txn,
)
from quicken_helper.data_model.interfaces import ITransaction
from quicken_helper.utilities import LOGGING

logging.config.dictConfig(LOGGING)
log = logging.getLogger(__name__)


@dataclass
class DataSession:
    """
    Centralizes file loading and in-memory data for GUI tabs.

    Responsibilities:
    • Load and memoize QIF transactions once per path.
    • Load and memoize Excel rows/groups and expose Excel-side transactions.
    • Provide lightweight invalidation when file paths change.
    """

    qif_path: Optional[Path] = None
    qif_txns: List[ITransaction] = field(default_factory=list)

    excel_path: Optional[Path] = None
    excel_rows: Optional[List] = None
    excel_groups: Optional[List[ExcelTxnGroup]] = None
    excel_txns: List[ExcelTransaction] = field(default_factory=list)

    def load_qif(self, path: Path, *, encoding: str = "utf-8") -> List[ITransaction]:
        path = Path(path)
        if self.qif_path != path or not self.qif_txns:
            log.info("Loading QIF: %s", path)
            self.qif_txns = list(load_transactions_protocol(path, encoding=encoding))
            self.qif_path = path
            log.debug("Loaded %d transactions from %s", len(self.qif_txns), path)
        else:
            log.debug(
                "Reusing cached QIF transactions for %s (%d txns)",
                path,
                len(self.qif_txns),
            )
        return self.qif_txns

    def load_excel(self, path: Path) -> List[ExcelTransaction]:
        path = Path(path)
        if self.excel_path != path or not self.excel_txns:
            log.info("Loading Excel: %s", path)
            rows = mex.load_excel_rows(path)
            groups = mex.group_excel_rows(rows)
            txns = [map_group_to_excel_txn(g) for g in groups]
            self.excel_path = path
            self.excel_rows = rows
            self.excel_groups = groups
            self.excel_txns = txns
            log.debug(
                "Loaded %d rows → %d groups → %d txns",
                len(rows),
                len(groups),
                len(txns),
            )
        else:
            log.debug(
                "Reusing cached Excel data for %s (%d txns)", path, len(self.excel_txns)
            )
        return self.excel_txns
