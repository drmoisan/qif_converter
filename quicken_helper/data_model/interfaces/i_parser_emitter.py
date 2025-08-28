# quicken_helper/data_model/interfaces/i_parser_emitter.py
"""
Generic, runtime-checkable protocol for bidirectional text ↔ object converters.

This protocol models a *pair* of operations over a specific Quicken-compatible
file format (e.g., QIF, QFX/OFX, CSV): a **parser** that converts a textual
representation into an iterable of domain objects, and an **emitter** that
serializes such objects back to text.

The protocol is generic in the item type ``T`` to allow strong typing at call
sites (e.g., ``IParserEmitter[ITransaction]``).  The type parameter is marked
*covariant* so that a producer of a more specific item type can be used where a
less specific type is expected.

### Design goals & expectations for implementers

- **Determinism:** Given the same input string, ``parse`` must produce the same
  sequence of items. Given the same items, ``emit`` must produce functionally
  equivalent text (byte-for-byte equality is ideal but not required if the
  format allows benign variations like whitespace).
- **Losslessness:** Round-tripping should hold as far as the target format
  allows. Prefer the invariant:

    ``emit(parse(s)) == normalize(s)``

  where ``normalize`` is the emitter’s canonical formatting of semantically
  equivalent input.
- **Order preservation:** ``parse`` should yield items in the order they appear
  in the source, unless the format specifies a different canonical order.
- **Purity:** ``parse`` and ``emit`` should avoid global state and not mutate
  arguments. If internal caches are used for performance, they must not affect
  observable results.
- **Errors:** On unrecoverable format errors, raise ``ValueError`` (or a
  documented subclass) with actionable context (line/column/range if possible).


Note: This is a **structural** type (``typing.Protocol``). Any class with
matching attributes/methods is considered compatible without explicit
inheritance.
"""

from __future__ import annotations

from typing import Iterable, Protocol, TypeVar, overload, runtime_checkable

from .enum_quicken_file_types import QuickenFileType

# Invariant item type produced by ``parse`` and consumed by ``emit``.
# Examples: a transaction interface (``ITransaction``), a header object,
#: or a union of supported record types for the target format.
T = TypeVar("T")


@runtime_checkable
class IParserEmitter(Protocol[T]):
    """
    Runtime-checkable protocol for paired parser/emitter implementations.

    Implementations convert between a *single* Quicken-like file format and
    a stream of strongly-typed items.

    Typical specializations include:

    - ``IParserEmitter[ITransaction]`` for transaction files (QIF/QFX/CSV)
    - ``IParserEmitter[Union[IAccount, ITransaction]]`` for mixed-section formats


    Overloads:

    - ``emit(items: Iterable[T]) -> str``
    - ``emit(items: T) -> str``

    Implementations may use a single signature `emit(items: Union[T, Iterable[T]]) -> str`.

    Attributes
    ----------
    file_format : QuickenFileType
        Identifier of the concrete file format handled by this implementation
        (e.g., ``QuickenFileType.QIF``). This is primarily used for feature
        gating, UI labeling, and dispatch at call sites. It should be a
        constant (per-class) value.

    Notes
    -----
    - Because this is a ``Protocol``, classes need not inherit from it; they
      only need to provide compatible attributes/methods.
    - The protocol is *runtime-checkable*, so ``isinstance(obj, IParserEmitter)``
      will return ``True`` for conforming objects.
    """

    file_format: QuickenFileType

    def parse(self, unparsed_string: str) -> Iterable[T]:
        """
        Parse a complete textual document into an iterable of items.

        Parameters
        ----------
        unparsed_string : str
            The full contents of the source document. Implementations should
            accept any valid Unicode content for the target format. If the
            format is logically line-oriented, line endings ``\\n``, ``\\r\\n``,
            and ``\\r`` must be treated equivalently.

        Returns
        -------
        Iterable[T]
            A finite iterable (often a list or generator) of parsed items, in
            document order unless the format specifies an alternate canonical
            order. Each item MUST satisfy the type ``T`` used to parameterize
            this protocol.

        Raises
        ------
        ValueError
            If the input cannot be parsed due to malformed content. Error
            messages should include enough context (e.g., line/column) to aid
            debugging.
        NotImplementedError
            If the implementation does not support a required feature of the
            declared ``file_format``.

        Notes
        -----
        - Implementers should avoid partial/implicit correction of malformed
          input unless such behavior is explicitly documented.
        - If the format contains multiple logical sections, the iterable may
          interleave item types, or you may choose to model ``T`` as a union.
        """

    @overload
    def emit(self, items: Iterable[T]) -> str:
        """
        Serialize an iterable of items into a single textual document.

        Parameters
        ----------
        items : Iterable[T]
            Items to serialize. Implementations may validate invariants (for
            example, that split amounts total to the parent amount) and should
            raise with context if violations are encountered.

        Returns
        -------
        str
            The emitted document as a Unicode string, formatted canonically
            (stable ordering, consistent whitespace/line endings) so that
            ``emit(parse(s))`` is stable modulo normalization.

        Raises
        ------
        ValueError
            If one or more items cannot be represented in the target format, or
            required fields are missing.
        NotImplementedError
            If the implementation does not support emitting specific features
            for the declared ``file_format``.

        Notes
        -----
        - Emitters should prefer ``\\n`` for line endings unless the ecosystem
          requires platform-native endings; this choice should be documented.
        - Implementers should not mutate ``items`` during emission.
        """

    @overload
    def emit(self, item: T) -> str:
        """
        Serialize an item of type ``T`` into a single textual document.

        Parameters
        ----------
        item : T
            Item to serialize. Implementations may validate invariants (for
            example, that split amounts total to the parent amount) and should
            raise with context if violations are encountered.

        Returns
        -------
        str
            The emitted document as a Unicode string, formatted canonically
            (stable ordering, consistent whitespace/line endings) so that
            ``emit(parse(s)[0])`` is stable modulo normalization.

        Raises
        ------
        ValueError
            If item cannot be represented in the target format, or
            required fields are missing.
        NotImplementedError
            If the implementation does not support emitting specific features
            for the declared ``file_format``.

        Notes
        -----
        - Emitters should prefer ``\\n`` for line endings unless the ecosystem
          requires platform-native endings; this choice should be documented.
        - Implementers should not mutate ``items`` during emission.
        """
