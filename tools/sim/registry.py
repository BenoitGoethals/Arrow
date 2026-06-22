"""Plugin registry for CoT message providers (Registry pattern).

Usage — add a provider at startup::

    from tools.sim.registry import registry, register_provider, CotMessageProvider
    from tools.sim.domain import CotEntry

    @register_provider
    class MyProvider(CotMessageProvider):
        category = "Custom"
        def get_messages(self) -> list[CotEntry]:
            return [CotEntry(uid="X.1", cot_type="a-f-G-U-C",
                             label="My unit", category="Custom",
                             callsign="X-1", lat=50.0, lon=4.0)]

Or register manually (useful when init args are required)::

    registry.register(MyProvider(some_arg))
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .domain import CotEntry


class CotMessageProvider(ABC):
    """Abstract base for a CoT message catalogue plugin.

    Subclass, set ``category`` as a class attribute, and implement
    ``get_messages``.  Register via ``@register_provider`` or
    ``registry.register(instance)``.
    """

    category: str = "Uncategorised"

    @abstractmethod
    def get_messages(self) -> list[CotEntry]: ...


class CotLibraryRegistry:
    """Holds all registered providers and exposes query methods.

    The module-level ``registry`` singleton is the recommended handle.
    """

    def __init__(self) -> None:
        self._providers: list[CotMessageProvider] = []

    def register(self, provider: CotMessageProvider) -> None:
        if not isinstance(provider, CotMessageProvider):
            raise TypeError(
                f"Expected CotMessageProvider, got {type(provider).__name__}"
            )
        self._providers.append(provider)

    def categories(self) -> list[str]:
        """Sorted list of unique category names across all providers."""
        return sorted({p.category for p in self._providers})

    def all_entries(self) -> list[CotEntry]:
        return [e for p in self._providers for e in p.get_messages()]

    def entries_for(self, category: str) -> list[CotEntry]:
        if category == "All":
            return self.all_entries()
        return [
            e
            for p in self._providers
            if p.category == category
            for e in p.get_messages()
        ]


# Module-level singleton — the only instance that should exist.
registry = CotLibraryRegistry()


def register_provider(cls: type[CotMessageProvider]) -> type[CotMessageProvider]:
    """Class decorator: instantiate *cls* and register it with the global registry.

    The decorated class is returned unchanged so it remains importable.
    """
    registry.register(cls())
    return cls
