from __future__ import annotations

from collections.abc import Iterable, Callable

from pyparsing import Empty

from quicken_helper.data_model import IAccount
from quicken_helper.data_model.interfaces import IParserEmitter, IQuickenFile, QuickenFileType
from quicken_helper.utilities.core_util import from_dict
from quicken_helper.data_model.q_wrapper import QuickenFile, QAccount
from itertools import pairwise  # Python 3.10+

class QifFileParserEmitter(IParserEmitter[IQuickenFile]):
    """Parse text into IQuickenFile objects and emit them back to text."""
    file_format: QuickenFileType = QuickenFileType.QIF

    def __init__(self, make_file: Callable[[], IQuickenFile] | None = None):
        self._make_file = make_file or QuickenFile  # default factory

    # --- required by IParserEmitter ---

    def parse(self, unparsed_string: str) -> Iterable[IQuickenFile]:
        """Return an iterable of IQuickenFile parsed from `unparsed_string`."""
        # build the concrete file(s)
        f = self._make_file()
        # ...fill f.sections/tags/accounts/transactions here...

        f.emitter = (
            self  # set back-reference (safe: typed as IParserEmitter[IQuickenFile])
        )
        return [f]

    def emit(self, obj: Iterable[IQuickenFile] | IQuickenFile) -> str:
        def _one(x: IQuickenFile) -> str:
            return x.emit_qif()  # use the model’s own emission

        if isinstance(obj, str) or not isinstance(obj, Iterable):
            return _one(obj)  # type: ignore[arg-type]
        return "\n".join(_one(x) for x in obj)

    # ------- internal parsing helpers -------

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
            "/": "balance_date", # Statement balance date
            "$": "balance_amount",  # Statement balance amount
        },
        "Category": {
            "N": "name",
            "D": "description",
            # Flags: lines that appear without values (e.g., E, I) become booleans.
            "E": ("flag", "expense"),
            "I": ("flag", "income"),
            "T": "tax_line",  # sometimes used for tax line info
            "B": "budget",  # if present, keep the value as-is
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

    def _split_on_caret(self, lines: list[str], keep_empty: bool = False) -> list[list[str]]:
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

        # Resolve auto-switch directives by peeking at the neighbor line
        if line.startswith(("!option:autoswitch", "!clear:autoswitch")):
            neighbor = (start + 1 if line.startswith("!option:autoswitch") else start - 1)
            line = norm(neighbor)
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
            if not pairs or pairs[-1][0] != key:
                pairs.append((key, i))

        # Add a sentinel end so we can slice with pairwise
        pairs.append(("\x00", len(lines)))

        # Slice each section and return as a dict
        return {k: lines[s:e] for (k, s), (_, e) in pairwise(pairs)}

    def parse_account_entry(
            self,
            field_map: dict[str, str] | dict[str, str | tuple[str, str]],
            entry_lines: list[str]
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
                raise ValueError(f"Unknown field code {code} while parsing account entry {'\r\n'.join(entry_lines)}")
            mapping = field_map.get(code)
            account_data[mapping] = value


        if "name" not in account_data or "type" not in account_data:
            return None

    def parse_accounts(self, lines: list[str]) -> list[IAccount]:
        field_map = self._FIELD_MAP.get("Account", {})
        cleaned_lines = self._preprocess_section(lines, drop_if_contains=["!Account","AutoSwitch"])
        entries = self._split_on_caret(cleaned_lines,keep_empty=False)
        if not entries:
            return []


        return []


    def _parse(self, unparsed_string: str) -> IQuickenFile:
        """Parse `unparsed_string` into a single IQuickenFile."""
        lines = unparsed_string.splitlines()
        sections = self.break_into_sections(lines)
        return QuickenFile()
        
