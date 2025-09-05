# quicken_helper/utilities/converters_collection.py
from __future__ import annotations

from collections import deque
from typing import Any, Callable


def _to_list(args, value, cv):
    (T,) = args or (object,)
    seq = list(value)  # let this raise if it's not iterable
    # (optional) guard: treat str/bytes as atomic, not iterable
    if isinstance(value, (str, bytes)):
        seq = [value]
    return [cv(T, v) for v in seq]


def _to_set(args, value, cv):
    (T,) = args or (object,)
    return {cv(T, v) for v in value}  # dedup by design


def _to_frozenset(args, value, cv):
    (T,) = args or (object,)
    return frozenset(cv(T, v) for v in value)


def _to_tuple(args, value, cv):
    seq = list(value)
    if not args:
        return tuple(seq)
    # tuple[T, ...] => homogeneous
    if len(args) == 2 and args[1] is Ellipsis:
        T = args[0]
        return tuple(cv(T, v) for v in seq)
    # tuple[T1, T2, ...] => fixed, heterogeneous
    if len(seq) != len(args):
        raise ValueError(f"Tuple arity mismatch: expected {len(args)}, got {len(seq)}")
    return tuple(cv(T, v) for T, v in zip(args, seq))


def _to_dict(args, value, cv):
    KT, VT = args or (object, object)
    items = dict(value).items()  # raises if not mapping-like
    return {cv(KT, k): cv(VT, v) for k, v in items}


def _to_deque(args, value, cv):
    (T,) = args or (object,)
    return deque(cv(T, v) for v in value)


CollectionConverter = Callable[[tuple[type, ...], Any, Callable[[Any, Any], Any]], Any]
COLLECTION_CONVERTERS: dict[type[Any], CollectionConverter] = {
    list: _to_list,
    set: _to_set,
    frozenset: _to_frozenset,
    tuple: _to_tuple,
    dict: _to_dict,
    deque: _to_deque,
}
