from enum import Enum


class QuickenFileType(Enum):
    """
    Enum representing the cleared status of a transaction.
    """
    QIF = "QIF"
    QFX = "QFX"
    OFX = "OFX"
    CSV = "CSV"
    UNKNOWN = "UNKNOWN"