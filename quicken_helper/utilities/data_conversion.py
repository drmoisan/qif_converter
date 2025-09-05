# quicken_helper/utilities/data_conversion.py

from quicken_helper.data_model.interfaces import ITransaction
from quicken_helper.utilities.core_util import convert_value


def as_transaction(x) -> ITransaction:
    # Leverage _PROTOCOL_IMPLEMENTATION map in core_util
    return convert_value(ITransaction, x)
