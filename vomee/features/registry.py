"""Feature registry — register/discover features by name (decorator based)."""
from __future__ import annotations

from typing import Callable, Dict, List, Type

from .base import Feature

_REGISTRY: Dict[str, Type[Feature]] = {}


def register(name: str) -> Callable[[Type[Feature]], Type[Feature]]:
    """Class decorator: ``@register("action")`` makes a Feature buildable via name."""

    def deco(cls: Type[Feature]) -> Type[Feature]:
        _REGISTRY[name] = cls
        return cls

    return deco


def available() -> List[str]:
    return sorted(_REGISTRY)


def create(name: str, **kwargs) -> Feature:
    if name not in _REGISTRY:
        raise KeyError(f"unknown feature '{name}'; available: {available()}")
    return _REGISTRY[name](**kwargs)
