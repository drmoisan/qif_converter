from enum import Enum
from functools import total_ordering

#from qif_converter.qif import qif_codes as codes


@total_ordering
class EnumClearedStatus(Enum):
    """
    Enum representing the cleared status of a transaction.
    """
    CLEARED = '*'  # Cleared
    NOT_CLEARED = 'N'  # Not cleared
    RECONCILED = 'R'  # Reconciled
    UNKNOWN = '?'  # Unknown status

    @classmethod
    def from_char(cls, char: str) -> 'EnumClearedStatus':
        """
        Convert a single character to a ClearedStatus enum.
        """
        for status in cls:
            if status.value == char:
                return status
        if char.strip() == "":
            return cls.NOT_CLEARED
        if char.lower() == "x":
            return cls.RECONCILED
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
        if not isinstance(other, EnumClearedStatus):
            return NotImplemented
        return self.value == other.value

    def __lt__(self, other: object):
        """
        Compare two ClearedStatus enums based on their order.
        """
        if not isinstance(other, EnumClearedStatus):
            return NotImplemented
        if self.value == other.value:
            return False
        elif self == EnumClearedStatus.RECONCILED:
            return True
        elif other == EnumClearedStatus.RECONCILED:
            return False
        elif self == EnumClearedStatus.CLEARED:
            return True
        else:
            return False
