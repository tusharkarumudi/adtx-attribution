"""Collectors. Importing this package registers all built-ins."""
from . import analytics, base, business, infra, records, registries  # noqa: F401
from .base import Collector, build_all, register, registry  # noqa: F401
