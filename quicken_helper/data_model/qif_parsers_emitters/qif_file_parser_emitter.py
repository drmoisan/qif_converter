from __future__ import annotations

import logging
import logging.config
import re
from collections.abc import Callable, Iterable
from itertools import pairwise  # Python 3.10+
from typing import Any, Dict, List, Tuple

from pyparsing import Empty

from quicken_helper.data_model import EnumClearedStatus, ICategory, QCategory
from quicken_helper.data_model.interfaces import (
    IAccount,
    IHeader,
    IParserEmitter,
    IQuickenFile,
    ITag,
    ITransaction,
    QuickenFileType,
)
from quicken_helper.data_model.q_wrapper import (
    QAccount,
    QifHeader,
    QSplit,
    QTag,
    QTransaction,
    QuickenFile,
)
from quicken_helper.utilities import LOGGING
from quicken_helper.utilities.core_util import (
    from_dict,
    is_null_or_whitespace,
)

logging.config.dictConfig(LOGGING)

log = logging.getLogger(__name__)


class QifFileParserEmitter(IParserEmitter[IQuickenFile]):
    """Parse text into IQuickenFile objects and emit them back to text."""

    file_format: QuickenFileType = QuickenFileType.QIF

    def __init__(self, make_file: Callable[[], IQuickenFile] | None = None):
        self._make_file = make_file or QuickenFile  # default factory

    # --- required by IParserEmitter ---

    def parse(self, unparsed_string: str) -> IQuickenFile:
        """Return an iterable of IQuickenFile parsed from `unparsed_string`."""
        # build the concrete file(s)
        f = self._make_file()
        # ...fill f.sections/tags/accounts/transactions here...
        # /m in Python -> re.MULTILINE; /g -> use finditer to get all matches
        self._PATTERN = re.compile(
            r"^(!Account[^\^]+\^\r?\n!Type:[^\r\n]+\r?\n)([^!]*)",
            flags=re.MULTILINE,
        )
        f = self._parse(unparsed_string)
        f.emitter = (
            self  # set back-reference (safe: typed as IParserEmitter[IQuickenFile])
        )
        return f

    def emit(self, obj: Iterable[IQuickenFile] | IQuickenFile) -> str:
        def _one(x: IQuickenFile) -> str:
            return x.emit_qif()  # use the model’s own emission

        if isinstance(obj, str) or not isinstance(obj, Iterable):
            return _one(obj)  # type: ignore[arg-type]
        return "\n".join(_one(x) for x in obj)

    # ------- internal parsing helpers -------

    _PROTOCOL_IMPLEMENTATION = {
        IQuickenFile: QuickenFileType,
        ITransaction: QTransaction,
        ITag: QTag,
        IAccount: QAccount,
        ICategory: QCategory,
        IHeader: QifHeader,
    }

    _SECTION_NORMALIZE = {
        "!account": "Account",
        "!type:cat": "Category",
        "!type:category": "Category",
        "!type:memorized": "Memorized",
        "!type:memorized payee": "Memorized",
        "!type:security": "Security",
        "!type:tag": "Tag",
        "!type:cash": "Transaction",
        "!type:bank": "Transaction",
        "!type:ccard": "Transaction",
        "!type:oth a": "Transaction",
        "!type:oth l": "Transaction",
        "!type:invst": "Transaction",
    }

    _FIELD_MAP = {
        "Account": {
            "N": "name",
            "D": "description",
            "T": "type",
            "L": "limit",  # Credit limit for credit card accounts
            "/": "balance_date",  # Statement balance date
            "$": "balance_amount",  # Statement balance amount
        },
        "Category": {
            "N": "name",
            "D": "description",
            "E": "expense_category",  # boolean
            "I": "income_category",  # boolean
            "T": "tax_related",  # boolean
            "R": "tax_schedule",
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
        "Tag": {
            "N": "name",
            "D": "description",
        },
        "Transaction": {
            "D": "date",
            "T": "amount",
            "U": "amount",
            "C": "cleared",
            "N": "action_chk",
            "P": "payee",
            "M": "memo",
            "L": "category",
        },
        "SecurityTransaction": {
            "Y": "security_name",  # security name (for invst)
            "I": "price",  # price per share (for invst)
            "Q": "quantity",  # number of shares (for invst)
            "O": "commission",  # commission (for invst)
            "$": "transfer_amount",  # amount transferred (for invst)
        },
        "Split": {
            "S": "category",
            "E": "memo",
            "$": "amount",
        },
        "Payee": {
            "N": "name",
            "A": "address",
            "M": "memo",
        },
    }

    def _preprocess_section(
        self,
        lines: list[str],
        drop_if_contains: list[str] | None = None,
    ) -> list[str]:
        """
        Normalize a section’s lines for lossless parsing while preserving case,
        and optionally drop lines containing disallowed substrings.

        Normalization (split–join) does the following:
          - Replace any literal CR/LF characters that appear within a line with a space.
          - Collapse all runs of whitespace to a single space via ``str.split()`` / ``" ".join(...)``.
          - Strip leading/trailing whitespace.
          - Drop lines that normalize to empty.

        After normalization, any line that contains *any* string from ``drop_if_contains``
        as a substring (case-sensitive) is removed.

        Args:
            lines: Raw input lines (one element per original line).
            drop_if_contains: Optional list of substrings; if any is found in a
                normalized line, that line is omitted. Use an empty list or None to disable.

        Returns:
            A new list of normalized, non-empty lines with disallowed lines removed.
        """
        banned = tuple(drop_if_contains or ())
        return [
            s
            for s in (
                " ".join(ln.replace("\r", " ").replace("\n", " ").split())
                for ln in lines
            )
            if s and not any(b in s for b in banned)
        ]

    def _split_on_caret(
        self, lines: list[str], keep_empty: bool = False
    ) -> list[list[str]]:
        """
        Split a list of lines into records using a line that is exactly "^" as the delimiter.

        Args:
            lines: Input lines (each string is one full line).
            keep_empty: If True, include empty records created by consecutive "^" lines
                or a leading "^". A trailing "^" does *not* produce an extra empty record.

        Returns:
            A list of records, where each record is a list of lines between delimiters.
        """
        cuts = [-1] + [i for i, ln in enumerate(lines) if ln == "^"] + [len(lines)]
        return [
            lines[i + 1 : j]
            for i, j in zip(cuts, cuts[1:])
            if keep_empty or (i + 1 < j)
        ]

    def _is_account_list(self, lines: list[str], start: int) -> bool:
        """Heuristic to determine if lines starting at `start` is an account list.
        Look ahead to see if it's an account list or transaction.
        """
        # The logic here is that an account list starts with !Account, but
        # contains more than one entry. If the 4th line after start begins with
        # !Type:, then it's likely a transaction section, not an account list.
        return not (start + 4 < len(lines) and lines[start + 4].startswith("!Type:"))

    def _get_header_indices(self, lines: list[str]) -> list[int]:
        """Return the indices of lines that start with '!'."""
        return [i for i, line in enumerate(lines) if line.startswith("!")]

    def _classify_header_type(self, lines: list[str], start: int) -> str:
        """Classify the section type starting at `lines[start]`."""

        # Normalize the line to lowercase and strip whitespace, checking for bounds
        def norm(i: int) -> str | None:
            return lines[i].strip().lower() if 0 <= i < len(lines) else None

        line = norm(start)
        if line is None:
            return "Unknown"

        if line.startswith("!clear:autoswitch"):
            return "skip"
        # Resolve auto-switch directives by peeking at the neighbor line
        if line.startswith("!option:autoswitch"):
            start += 1
            line = norm(start)
            if line is None:
                return "Unknown"

        # Resolve Account by peeking ahead to see if it's an account list or transaction
        if line.startswith("!account"):
            return "Account" if self._is_account_list(lines, start) else "Transaction"

        # Resolve other sections using the normalization map
        return self._SECTION_NORMALIZE.get(line, "Unknown")

    def break_into_sections(self, lines: list[str]) -> dict[str, list[str]]:
        """Break `lines` into sections based on headers starting with '!'.
        Returns a dict mapping section keys to their corresponding lines.
        """
        # Get indices of header lines
        starts = self._get_header_indices(lines)

        # Ensure we always start at 0 even if no header there
        if not starts or starts[0] != 0:
            starts = [0, *starts]

        # Build (section_key, start_index) pairs, collapsing consecutive duplicates
        pairs: list[tuple[str, int]] = []
        for i in starts:
            key = self._classify_header_type(lines, i)
            if key != "skip" and (not pairs or pairs[-1][0] != key):
                pairs.append((key, i))

        # Add a sentinel end so we can slice with pairwise
        pairs.append(("\x00", len(lines)))

        # Slice each section and return as a dict
        return {k: lines[s:e] for (k, s), (_, e) in pairwise(pairs)}

    def parse_account_entry(
        self, field_map: dict, entry_lines: list[str]
    ) -> IAccount | None:
        """Parse a single account entry from its lines into an IAccount object."""
        if not entry_lines or field_map is Empty:
            return None
        account_data = {}
        for line in entry_lines:
            if not line:
                continue
            code = line[0]
            value = line[1:].strip() if len(line) > 1 else ""
            if code not in field_map:
                raise ValueError(
                    f"Unknown field code {code} while parsing account entry {'\r\n'.join(entry_lines)}"
                )
            mapping = field_map.get(code)
            account_data[mapping] = value

        try:
            account = from_dict(QAccount, account_data)
            return account
        except Exception as e:
            log.exception(
                f"Error constructing IAccount from data {account_data}\nException: {e}"
            )
            return None

    def parse_accounts(self, lines: list[str]) -> list[IAccount]:
        field_map: dict = self._FIELD_MAP.get("Account", {})
        cleaned_lines = self._preprocess_section(
            lines, drop_if_contains=["!Account", "AutoSwitch"]
        )
        entries = self._split_on_caret(cleaned_lines, keep_empty=False)
        if not entries:
            return []
        accounts = [
            account
            for entry in entries
            if (account := self.parse_account_entry(field_map, entry)) is not None
        ]
        return accounts

    def parse_categories(self, lines: list[str]) -> list[ICategory]:
        field_map: dict = self._FIELD_MAP.get("Category", {})
        cleaned_lines = self._preprocess_section(
            lines, drop_if_contains=["!Type:Cat", "AutoSwitch"]
        )
        entries = self._split_on_caret(cleaned_lines, keep_empty=False)
        if not entries:
            return []
        categories = [
            category
            for entry in entries
            if (category := self.parse_category_entry(field_map, entry)) is not None
        ]
        return categories

    def parse_category_entry(
        self, field_map: dict, entry_lines: list[str]
    ) -> ICategory | None:
        if not entry_lines or field_map is Empty:
            return None
        data = {}
        for line in entry_lines:
            if not line:
                continue
            code = line[0]
            value = line[1:].strip() if len(line) > 1 else ""
            if code not in field_map:
                raise ValueError(
                    f"Unknown field code {code} while parsing tag entry {'\r\n'.join(entry_lines)}"
                )
            mapping = field_map.get(code)
            if mapping in ["expense_category", "income_category", "tax_related"]:
                data[mapping] = True
            else:
                data[mapping] = value
        try:
            typed_object = from_dict(QCategory, data)
            return typed_object
        except Exception as e:
            log.exception(
                f"Error constructing IAccount from data {data}\nException: {e}"
            )
            return None

    def parse_tag_entry(self, field_map: dict, entry_lines: list[str]) -> ITag | None:
        if not entry_lines or field_map is Empty:
            return None
        tag_data = {}
        for line in entry_lines:
            if not line:
                continue
            code = line[0]
            value = line[1:].strip() if len(line) > 1 else ""
            if code not in field_map:
                raise ValueError(
                    f"Unknown field code {code} while parsing tag entry {'\r\n'.join(entry_lines)}"
                )
            mapping = field_map.get(code)
            tag_data[mapping] = value
        try:
            tag = from_dict(QTag, tag_data)
            return tag
        except Exception as e:
            log.exception(
                f"Error constructing IAccount from data {tag_data}\nException: {e}"
            )
            return None

    def parse_tags(self, lines: list[str]) -> list[ITag]:
        field_map: dict = self._FIELD_MAP.get("Tag", {})
        cleaned_lines = self._preprocess_section(lines, drop_if_contains=["!Type:Tag"])
        entries = self._split_on_caret(cleaned_lines, keep_empty=False)
        if not entries:
            return []
        tags = [
            tag
            for entry in entries
            if (tag := self.parse_tag_entry(field_map, entry)) is not None
        ]
        return tags

    def _normalize_group_0(self, text: str) -> Tuple[IAccount, IHeader] | None:
        account_map = self._FIELD_MAP.get("Account", {})
        lines = text.splitlines()
        cleaned_lines = self._preprocess_section(lines, drop_if_contains=["!Account"])
        entries = self._split_on_caret(cleaned_lines, keep_empty=False)
        if not entries or len(entries) != 2:
            raise ValueError(
                f"Expected !Account and !Type separated by ^. Malformed QIF?\n{text}"
            )
        account = self.parse_account_entry(account_map, entries[0])
        header = QifHeader(entries[1][0])
        return account, header

    def _normalize_group_1(self, text: str) -> list[list[str]]:
        lines = text.splitlines()
        cleaned_lines = self._preprocess_section(lines)
        entries = self._split_on_caret(cleaned_lines, keep_empty=False)
        return entries

    def _normalize_group(
        self, group: Tuple[str, str]
    ) -> list[Tuple[IAccount, IHeader, list[str]]]:
        null0 = is_null_or_whitespace(group[0])
        null1 = is_null_or_whitespace(group[1])
        if null0 and null1:
            log.warning(
                "Empty group encountered in transaction parsing.\nGroup Header and Body are both empty."
                f" regex failure?\nGroup Header:{group[0]}\nGroup Body:{group[1]}\n\n"
            )
            return []
        elif null0:
            log.warning(
                f"Empty group header encountered in transaction parsing, but transaction has data."
                f" regex failure?\nGroup Header:\n{group[0]}\nGroup Body:\n{group[1]}\n\n"
            )
            return []
        elif null1:
            log.debug(
                "Empty group body encountered in transaction parsing, but header has data."
                " This may be valid if there are no transactions for the account.\n"
                "Group Header:\n{group[0]}\n\nGroup Body:\n{group[1]}\n"
            )
            return []

        account, header = self._normalize_group_0(group[0])
        entries = self._normalize_group_1(group[1])
        transaction_tuples = [(account, header, entry) for entry in entries if entry]
        return transaction_tuples

    def _extract_transaction_groups(self, text: str) -> List[Tuple[str, str]]:
        """
        Return [(group1, group2), ...] for each match of the pattern.
        """
        return [(m.group(1), m.group(2)) for m in self._PATTERN.finditer(text)]

    def _parse_transaction_entry(
        self, field_map: dict, entry: Tuple[IAccount, IHeader, list[str]]
    ) -> ITransaction | None:
        rec: Dict[str, Any] = {}
        rec["account"] = entry[0]
        rec["type"] = entry[1]
        lines = entry[2]
        security_map = self._FIELD_MAP.get("SecurityTransaction", {})
        split_map = self._FIELD_MAP.get("Split", {})
        is_security_transaction = rec["type"].code.lower().startswith("!type:invst")
        security_data = {}
        splits = []
        pending_split = None

        for line in lines:
            if not line:
                continue

            code = line[0]
            value = line[1:].strip() if len(line) > 1 else ""
            if code in field_map:
                mapping = field_map.get(code)
                if mapping == "category" and "/" in value:
                    [rec["category"], rec["tag"]] = value.split("/")
                elif mapping == "cleared":
                    rec[mapping] = EnumClearedStatus.from_char(value)
                else:
                    rec[mapping] = value
            elif is_security_transaction and code in security_map:
                mapping = security_map.get(code)
                security_data[mapping] = value
            elif code in split_map:
                mapping = split_map.get(code)
                if mapping == "category":
                    if pending_split:
                        splits.append(pending_split)
                    pending_split = {}
                    if mapping == "category" and "/" in value:
                        [pending_split["category"], pending_split["tag"]] = value.split(
                            "/"
                        )
                    else:
                        pending_split[mapping] = value
                else:
                    pending_split[mapping] = value
            else:
                raise ValueError(
                    f"Unknown field code {code} while parsing transaction entry {'\r\n'.join(lines)}"
                )
        if pending_split:
            splits.append(pending_split)
        if len(splits) > 0:
            try:
                rec["splits"] = [from_dict(QSplit, s) for s in splits if s]
            except Exception as e:
                log.exception(
                    f"Error constructing ISplit from data {splits}\nException: {e}"
                )
                raise ValueError(
                    f"Error constructing ISplit from data {splits}\nException: {e}"
                )
        if is_security_transaction and security_data:
            try:
                rec["_security"] = from_dict(QTag, security_data)
            except Exception as e:
                log.exception(
                    f"Error constructing ISecurity from data {security_data}\nException: {e}"
                )
                raise ValueError(
                    f"Error constructing ISecurity from data {security_data}\nException: {e}"
                )

        if "cleared" not in rec:
            rec["cleared"] = EnumClearedStatus.NOT_CLEARED
        # try:
        transaction = from_dict(QTransaction, rec)
        # except Exception as e:
        #     log.exception(f"Error constructing ITransaction from data {rec}\nException: {e}")
        #     raise ValueError(f"Error constructing ITransaction from data {rec}\nException: {e}")

        return transaction

    def parse_transactions(self, lines: list[str]) -> list[ITransaction]:
        field_map: dict = self._FIELD_MAP.get("Transaction", {})
        text_block = "\n".join(lines)
        groups = self._extract_transaction_groups(text_block)
        normalized_groups = [self._normalize_group(g) for g in groups]
        # Flatten the list of lists
        entries = [tup for sublist in normalized_groups for tup in sublist]
        transactions = [
            self._parse_transaction_entry(field_map, entry)
            for entry in entries
            if entry
        ]
        return transactions

    def _parse(self, unparsed_string: str) -> IQuickenFile:
        """Parse `unparsed_string` into a single IQuickenFile."""
        lines = unparsed_string.splitlines()
        sections = self.break_into_sections(lines)
        qf = QuickenFile()
        if "Account" in sections:
            qf.accounts = self.parse_accounts(sections["Account"])
        if "Tag" in sections:
            qf.tags = self.parse_tags(sections["Tag"])
        if "Category" in sections:
            qf.categories = self.parse_categories(sections["Category"])
        if "Transaction" in sections:
            qf.transactions = self.parse_transactions(sections["Transaction"])
        return qf
