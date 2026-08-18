"""Collectors. Importing this package registers all built-ins.

Persona collectors register too, but registration is not enablement -- the
engine gates them on the case file's two keys. Their optional dependencies are
imported lazily inside each collector, so the package imports cleanly without
the ``persona`` extra installed.
"""
from . import analytics, base, business, infra, persona, records, registries  # noqa: F401
from .base import Collector, build_all, register, registry  # noqa: F401

#: Names the engine treats as person-scoped. Registered with attribution-graph
#: on import so the gate applies wherever these collectors are used.
PERSONA_COLLECTOR_NAMES = frozenset({
    "gravatar", "github_intel", "username_expand", "holehe", "pgp_wkd",
})

try:  # pragma: no cover
    from attribution_graph import PERSON_SCOPED_COLLECTORS
    PERSON_SCOPED_COLLECTORS.update(PERSONA_COLLECTOR_NAMES)
except ImportError:  # pragma: no cover
    pass
