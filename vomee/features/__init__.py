"""Extensible sensing algorithms (heartbeat, action recognition, ...).

Concrete features are added in later phases (Phase B heartbeat, Phase C action model);
this package defines the :class:`Feature` ABC and the registry they plug into.
"""
from .base import Feature
from .registry import available, create, register

# Import the built-in feature stubs so they self-register (Phase B/C fill them in).
from . import action_classifier, heartbeat  # noqa: E402,F401

__all__ = ["Feature", "register", "available", "create"]
