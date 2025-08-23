# qif_converter/qif_loader.py
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Re-use your established transaction parser (handles splits etc.)
from .qif_parsed import ParsedQIF
from .utilities.core_util import _open_for_read, QIF_SECTION_PREFIX, QIF_ACCOUNT_HEADER, TRANSFER_RE


# --------------------------
# Unified, robust QIF loader
# --------------------------
def parse_qif_unified(path: Path, encoding: str = "utf-8") -> ParsedQIF:
    """
    Unified QIF loader.
    - Transactions: delegated to parse_qif (your current canonical parser).
    - Lists (Accounts, Categories, Memorized, Securities, Class/Business, Payees): parsed here,
      tolerant to format variants; unknown sections are preserved in other_sections.
    """
    # 1) Always use your mature parser for transactions
    transactions = parse_qif(path, encoding=encoding)

    # 2) Parse other sections defensively
    (
        accounts,
        categories,
        memorized,
        securities,
        business_or_class,
        payees,
        other_sections,
    ) = _parse_non_txn_sections(path, encoding=encoding)

    return ParsedQIF(
        transactions=transactions,
        accounts=accounts,
        categories=categories,
        memorized_payees=memorized,
        securities=securities,
        business_list=business_or_class,
        payees=payees,
        other_sections=other_sections,
    )

def load_transactions(path: Path, encoding: str = "utf-8") -> List[Dict[str, Any]]:
    """Convenience: return only transactions from a unified parse."""
    return parse_qif_unified(path, encoding=encoding).transactions


# --------------------------------------
# Internal helpers for non-transactional
# --------------------------------------
# Known section headers (seen in the wild, plus tolerant synonyms)
_SECTION_NORMALIZE = {
    "!account": "Account",
    "!type:cat": "Category",
    "!type:category": "Category",
    "!type:memorized": "Memorized",
    "!type:memorized payee": "Memorized",
    "!type:security": "Security",
    "!type:class": "Class",  # business/class list
    "!type:payee": "Payee",
}

# A minimal single-char → key map per section family.
# Unrecognized letters are placed under 'raw'.
_FIELD_MAP = {
    "Account": {
        "N": "name",
        "D": "description",
        "T": "type",
        "L": "limit",  # not standard everywhere; store if present
    },
    "Category": {
        "N": "name",
        "D": "description",
        # Flags: lines that appear without values (e.g., E, I) become booleans.
        "E": ("flag", "expense"),
        "I": ("flag", "income"),
        "T": "tax_line",  # sometimes used for tax line info
        "B": "budget",    # if present, keep the value as-is
    },
    "Memorized": {
        "N": "name",
        "M": "memo",
        "T": "type",  # type of txn (payment, deposit, etc.)
        "A": "address",  # can repeat; we’ll join lines
        "L": "category",
    },
    "Security": {
        "N": "name",
        "S": "symbol",
        "T": "type",
        "D": "description",
    },
    "Class": {
        "N": "name",
        "D": "description",
    },
    "Payee": {
        "N": "name",
        "A": "address",
        "M": "memo",
    },
}

def _parse_non_txn_sections(
    path: Path, encoding: str = "utf-8"
) -> Tuple[
    List[Dict[str, Any]],  # accounts
    List[Dict[str, Any]],  # categories
    List[Dict[str, Any]],  # memorized
    List[Dict[str, Any]],  # securities
    List[Dict[str, Any]],  # business/class
    List[Dict[str, Any]],  # payees
    Dict[str, List[Dict[str, Any]]],  # other/unknown
]:
    accounts: List[Dict[str, Any]] = []
    categories: List[Dict[str, Any]] = []
    memorized: List[Dict[str, Any]] = []
    securities: List[Dict[str, Any]] = []
    classes: List[Dict[str, Any]] = []
    payees: List[Dict[str, Any]] = []
    other_sections: Dict[str, List[Dict[str, Any]]] = {}

    def push(section_name: str, entry: Dict[str, Any]) -> None:
        if section_name == "Account":
            accounts.append(entry)
        elif section_name == "Category":
            categories.append(entry)
        elif section_name == "Memorized":
            memorized.append(entry)
        elif section_name == "Security":
            securities.append(entry)
        elif section_name == "Class":
            classes.append(entry)
        elif section_name == "Payee":
            payees.append(entry)
        else:
            other_sections.setdefault(section_name, []).append(entry)

    current_section: Optional[str] = None
    cur_entry: Optional[Dict[str, Any]] = None

    def commit_entry():
        nonlocal cur_entry
        if current_section and cur_entry is not None:
            push(current_section, cur_entry)
        cur_entry = None

    with path.open("r", encoding=encoding, errors="ignore") as f:
        for raw in f:
            line = raw.rstrip("\n\r")
            if not line:
                continue

            if line.startswith("!"):  # Start of a new section
                # Close previous entry when switching sections
                commit_entry()
                current_section = _SECTION_NORMALIZE.get(line.strip().lower(), line.strip()[1:])
                # For unknown sections, we'll still parse entries generically into other_sections
                continue

            if line == "^":  # End of current entry
                commit_entry()
                continue

            # If we are not in a non-txn section of interest, ignore the content
            if not current_section:
                continue

            # Start a new entry lazily when first data line arrives
            if cur_entry is None:
                cur_entry = {"raw": []}

            # Try to parse single-letter field code (like QIF normally does)
            # e.g., "NCategory Name" → code "N", value "Category Name"
            code = line[:1]
            value = line[1:]
            cur_entry["raw"].append(line)

            fmap = _FIELD_MAP.get(current_section, {})
            mapping = fmap.get(code)

            if mapping is None:
                # Not in map: just keep under 'raw_<code>' so data is never lost
                cur_entry.setdefault(f"raw_{code}", []).append(value)
                continue

            if isinstance(mapping, tuple) and mapping[0] == "flag":
                # Boolean flags: presence of code implies True
                cur_entry[mapping[1]] = True
                continue

            key = mapping

            if code in ("A",):  # address lines can repeat → join
                cur_entry.setdefault(key, []).append(value)
                continue

            # Normal scalar assignment; if repeats, keep last and store repeats in extras
            if key in cur_entry:
                cur_entry.setdefault(f"{key}_extra", []).append(value)
            cur_entry[key] = value

    # Normalize joined multi-line fields
    for col in (accounts, categories, memorized, securities, classes, payees):
        for e in col:
            if isinstance(e.get("address"), list):
                e["address"] = "\n".join(e["address"])

    return accounts, categories, memorized, securities, classes, payees, other_sections


def parse_qif(path: Path, encoding: str = "utf-8") -> List[Dict[str, Any]]:
    """Parse a QIF file into a list of transaction dicts."""
    txns: List[Dict[str, Any]] = []
    current_type: Optional[str] = None
    current_account: Optional[str] = None
    in_account_block = False
    account_props: Dict[str, str] = {}

    def finalize_tx(rec: Dict[str, Any]) -> None:
        if not rec:
            return
        rec.setdefault("account", current_account)
        rec.setdefault("type", current_type)
        if not rec.get("transfer_account"):
            cat = (rec.get("category") or "").strip()
            m = TRANSFER_RE.match(cat)
            rec["transfer_account"] = m.group(1) if m else ""
        addr_lines = rec.pop("_address_lines", None)
        rec["address"] = "\n".join(addr_lines) if addr_lines else ""
        for k in ("amount", "quantity", "price", "commission"):
            rec.setdefault(k, "")
        rec.setdefault("splits", [])
        txns.append(rec)

    with _open_for_read(path=path,binary=False,encoding=encoding,errors="replace") as f:
    #with path.open("r", encoding=encoding, errors="replace") as f:
        rec: Dict[str, Any] = {}
        pending_split: Optional[Dict[str, str]] = None
        for raw_line in f:
            line = raw_line.rstrip("\r\n").lstrip()
            if not line:
                continue
            if line.startswith(QIF_SECTION_PREFIX):
                if rec:
                    finalize_tx(rec); rec = {}; pending_split = None
                current_type = line[len(QIF_SECTION_PREFIX):].strip()
                in_account_block = False
                continue
            if line.startswith(QIF_ACCOUNT_HEADER):
                if rec:
                    finalize_tx(rec); rec = {}; pending_split = None
                in_account_block = True
                account_props = {}
                continue
            if line.strip() == "^":
                if in_account_block:
                    current_account = account_props.get("N") or account_props.get("name") or current_account
                    in_account_block = False; account_props = {}
                else:
                    if pending_split is not None:
                        rec.setdefault("splits", []).append(pending_split)
                        pending_split = None
                    finalize_tx(rec); rec = {}
                continue
            if in_account_block:
                code = line[:1]; value = line[1:].rstrip()
                account_props[code] = value
                continue

            code = line[:1]
            value = line[1:].rstrip()
            if code == "D":
                rec["date"] = value
            elif code == "T":
                rec["amount"] = value
            elif code == "P":
                rec["payee"] = value
            elif code == "M":
                prior = rec.get("memo", "")
                rec["memo"] = (prior + "\n" + value).strip() if prior else value
            elif code == "L":
                rec["category"] = value
                m = TRANSFER_RE.match(value.strip())
                rec["transfer_account"] = (m.group("acct").strip() if m else rec.get("transfer_account", ""))

            elif code == "N":
                if current_type and str(current_type).lower().startswith("invst"):
                    rec["action"] = value
                else:
                    rec["checknum"] = value
            elif code == "C":
                rec["cleared"] = value
            elif code == "A":
                value = value.replace("\\n", "\n")
                rec.setdefault("_address_lines", []).append(value)
            elif code == "Y":
                rec["security"] = value
            elif code == "Q":
                rec["quantity"] = value
            elif code == "I":
                rec["price"] = value
            elif code == "O":
                rec["commission"] = value
            elif code == "S":
                if pending_split is not None:
                    rec.setdefault("splits", []).append(pending_split)
                pending_split = {"category": value, "memo": "", "amount": ""}
            elif code == "E":
                if pending_split is None:
                    pending_split = {"category": "", "memo": value, "amount": ""}
                else:
                    pending_split["memo"] = value
            elif code == "$":
                if pending_split is None:
                    pending_split = {"category": "", "memo": "", "amount": value}
                else:
                    pending_split["amount"] = value
            else:
                pass
        if rec:
            finalize_tx(rec)
    return txns
