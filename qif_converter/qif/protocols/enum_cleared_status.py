from enum import Enum
from functools import total_ordering

#from qif_converter.qif import qif_codes as codes


@total_ordering
class ClearedStatus(Enum):
    """
    Enum representing the cleared status of a transaction.
    """
    CLEARED = '*'  # Cleared
    NOT_CLEARED = 'N'  # Not cleared
    RECONCILED = 'R'  # Reconciled
    UNKNOWN = '?'  # Unknown status

    @classmethod
    def from_char(cls, char: str) -> 'ClearedStatus':
        """
        Convert a single character to a ClearedStatus enum.
        """
        for status in cls:
            if status.value == char:
                return status
        raise ValueError(f"Unknown cleared status character: {char}")

    # def emit_qif(self) -> str:
    #     """
    #     Returns the QIF representation of this cleared status.
    #     """
    #     if self == ClearedStatus.NOT_CLEARED or self == ClearedStatus.UNKNOWN:
    #         return ""
    #     else:
    #         return f"{codes.ClearedStatus().code}{self.value}"

    def __eq__(self, other: object):
        """
        Check equality with another ClearedStatus.
        """
        if not isinstance(other, ClearedStatus):
            return NotImplemented
        return self.value == other.value

    def __lt__(self, other: object):
        """
        Compare two ClearedStatus enums based on their order.
        """
        if not isinstance(other, ClearedStatus):
            return NotImplemented
        if self.value == other.value:
            return False
        elif self == ClearedStatus.RECONCILED:
            return True
        elif other == ClearedStatus.RECONCILED:
            return False
        elif self == ClearedStatus.CLEARED:
            return True
        else:
            return False
