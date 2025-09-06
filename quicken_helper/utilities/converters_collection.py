# quicken_helper/utilities/converters_collection.py
from __future__ import annotations

from collections import deque
from typing import Any, Callable, cast


def _to_list(
    args: tuple[type, ...],
    value: Any,
    cv: Callable[[Any, Any], Any],
) -> list[Any]:
    """Convert *value* to a ``list[T]`` using the element converter ``cv``.

    - ``args``: a 1-tuple holding the target element type ``T``; if empty,
      defaults to ``object``.
    - ``value``: an iterable of elements; ``str``/``bytes``/``bytearray`` are treated as atomic.
    - ``cv``: callable that converts a single element to type ``T``.
    """
    T = args[0] if args else object
    # Treat text/bytes as atomic
    if isinstance(value, (str, bytes, bytearray)):
        seq = [value]
    else:
        # Require an iterable; raise a helpful error otherwise
        try:
            # We intentionally materialize to a list here for stable conversion semantics.
            seq = list(value)  # type: ignore[arg-type]
        except Exception as e:
            raise TypeError(
                f"Expected an iterable for list conversion; got {type(value).__name__}"
            ) from e
    return [cv(T, v) for v in seq]


def _to_set(
    args: tuple[type, ...],
    value: Any,
    cv: Callable[[Any, Any], Any],
) -> set[Any]:
    """Convert *value* to a ``set[T]`` using the element converter ``cv``.

    - ``args``: a 1-tuple holding the target element type ``T``; if empty,
      defaults to ``object``.
    - ``value``: an iterable of elements; ``str``/``bytes``/``bytearray`` are treated as atomic.
    - ``cv``: callable that converts a single element to type ``T``.
    """
    T = args[0] if args else object
    # Treat text/bytes as atomic (avoid character splitting)
    if isinstance(value, (str, bytes, bytearray)):
        seq = [value]
    else:
        try:
            seq = list(value)  # type: ignore[arg-type]
        except Exception as e:
            raise TypeError(
                f"Expected an iterable for set conversion; got {type(value).__name__}"
            ) from e
    try:
        return set(cv(T, v) for v in seq)
    except TypeError as e:
        # Most likely: element(s) are unhashable after conversion
        raise TypeError(
            "Unhashable element encountered while building set; "
            "ensure the converter returns hashable items for set[T]."
        ) from e


def _to_frozenset(
    args: tuple[type, ...],
    value: Any,
    cv: Callable[[Any, Any], Any],
) -> frozenset[Any]:
    """Convert *value* to a ``frozenset[T]`` using the element converter ``cv``.

    - ``args``: a 1-tuple holding the target element type ``T``; if empty,
      defaults to ``object``.
    - ``value``: an iterable of elements; ``str``/``bytes``/``bytearray`` are treated as atomic.
    - ``cv``: callable that converts a single element to type ``T``.
    """
    T = args[0] if args else object
    # Treat text/bytes as atomic (avoid character splitting)
    if isinstance(value, (str, bytes, bytearray)):
        seq = [value]
    else:
        try:
            seq = list(value)  # type: ignore[arg-type]
        except Exception as e:
            raise TypeError(
                f"Expected an iterable for frozenset conversion; got {type(value).__name__}"
            ) from e
    try:
        return frozenset(cv(T, v) for v in seq)
    except TypeError as e:
        # Most likely: element(s) are unhashable after conversion
        raise TypeError(
            "Unhashable element encountered while building frozenset; "
            "ensure the converter returns hashable items for frozenset[T]."
        ) from e


def _to_tuple(
    args: tuple[type, ...],
    value: Any,
    cv: Callable[[Any, Any], Any],
) -> tuple[Any, ...]:
    """Convert *value* to a ``tuple[T]`` using the element converter ``cv``.

    - ``args``: a 1-tuple holding the target element type ``T``; if empty,
      defaults to ``object``.
    - ``value``: an iterable of elements; ``str``/``bytes``/``bytearray`` are treated as atomic.
    - ``cv``: callable that converts a single element to type ``T``.
    """
    T = args[0] if args else object
    if isinstance(value, (str, bytes, bytearray)):
        seq = [value]
    else:
        try:
            seq = list(value)  # type: ignore[arg-type]
        except Exception as e:
            raise TypeError(
                f"Expected an iterable for tuple conversion; got {type(value).__name__}"
            ) from e
    return tuple(cv(T, v) for v in seq)


def _to_dict(
    args: tuple[type, ...],
    value: Any,
    cv: Callable[[Any, Any], Any],
) -> dict[Any, Any]:
    """Convert *value* to a ``dict[K, V]`` using the element converter ``cv``.

    Accepts either a mapping (uses ``.items()``) or an iterable of 2-item pairs.
    Text/bytes are rejected since they are not meaningful dict sources.

    - ``args``: a 2-tuple holding key and value target types ``(K, V)``; if
      missing, defaults to ``(object, object)``.
    - ``value``: mapping or iterable of pairs.
    - ``cv``: callable that converts a single element to the target type.
    """
    from collections.abc import Mapping

    K = args[0] if len(args) >= 1 else object
    V = args[1] if len(args) >= 2 else object

    items: list[tuple[Any, Any]]

    if isinstance(value, Mapping):
        # Cast to a typed Mapping so Pylance can infer K/V as Any rather than Unknown.
        m = cast(Mapping[Any, Any], value)
        items = list(m.items())  # list[tuple[Any, Any]]
    else:
        # Reject atomic text/bytes
        if isinstance(value, (str, bytes, bytearray)):
            raise TypeError(
                "Expected a mapping or iterable of 2-item pairs for dict conversion; got text/bytes."
            )
        try:
            raw_iter: list[Any] = list(value)  # type: ignore[arg-type]
        except Exception as e:
            raise TypeError(
                f"Expected a mapping or iterable of 2-item pairs for dict conversion; got {type(value).__name__}"
            ) from e

        pairs: list[tuple[Any, Any]] = []
        for idx, pair in enumerate(raw_iter):
            try:
                k, v = pair  # type: ignore[misc]
            except Exception:
                raise TypeError(
                    f"Element at index {idx} is not a 2-item pair: {pair!r}"
                )
            pairs.append((k, v))
        items = pairs

    # Build the dict with explicit annotations to avoid "Unknown" propagation.
    result: dict[Any, Any] = {}
    for k, v in items:
        ck: Any = cv(K, k)
        cvv: Any = cv(V, v)
        try:
            hash(ck)
        except Exception as e:
            raise TypeError(
                "Unhashable key encountered while building dict; "
                "ensure the converter returns hashable keys for dict[K, V]."
            ) from e
        result[ck] = cvv
    return result


def _to_deque(
    args: tuple[type, ...],
    value: Any,
    cv: Callable[[Any, Any], Any],
) -> deque[Any]:
    """Convert *value* to a ``deque[T]`` using the element converter ``cv``.

    - ``args``: a 1-tuple holding the target element type ``T``; if empty,
      defaults to ``object``.
    - ``value``: an iterable of elements; ``str``/``bytes``/``bytearray`` are treated as atomic.
    - ``cv``: callable that converts a single element to type ``T``.
    """
    T = args[0] if args else object
    if isinstance(value, (str, bytes, bytearray)):
        seq = [value]
    else:
        try:
            seq = list(value)  # type: ignore[arg-type]
        except Exception as e:
            raise TypeError(
                f"Expected an iterable for deque conversion; got {type(value).__name__}"
            ) from e
    return deque(cv(T, v) for v in seq)


CollectionConverter = Callable[[tuple[type, ...], Any, Callable[[Any, Any], Any]], Any]
COLLECTION_CONVERTERS: dict[type[Any], CollectionConverter] = {
    list: _to_list,
    set: _to_set,
    frozenset: _to_frozenset,
    tuple: _to_tuple,
    dict: _to_dict,
    deque: _to_deque,
}
