"""Registry catalog: what exists, where, and whether it can be automated.

Most corporate and land registries in the world are not automatable. They are
captcha-gated, session-bound, paid-per-search, or robots-disallowed. A catalog
that quietly omits those is worse than useless during an investigation, because
the analyst concludes no source exists when one does.

So the catalog records everything and marks ``automatable: false`` where a human
has to go look. The collector layer refuses to fetch those entries; the CLI
prints them so you know where to go by hand.

    adtx registries --jurisdiction IN
    adtx registries --yields beneficial_owner --automatable
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CATALOG_PATH = Path(__file__).parent / "data" / "registries.yaml"


@dataclass(frozen=True)
class Registry:
    jurisdiction: str
    name: str
    category: str
    scope: str = ""
    url: str = ""
    access: str = "manual"
    automatable: bool = False
    collector: str = ""
    auth_env: str = ""
    yields: tuple[str, ...] = field(default_factory=tuple)
    licence: str = ""
    rate_limit: str = ""
    notes: str = ""

    @property
    def needs_key(self) -> bool:
        return bool(self.auth_env)

    @property
    def status(self) -> str:
        if self.collector:
            return "implemented"
        if self.automatable:
            return "automatable, not implemented"
        return "manual lookup only"


@lru_cache(maxsize=1)
def load_catalog(path: str | Path = CATALOG_PATH) -> tuple[Registry, ...]:
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text())
    out: list[Registry] = []
    for category, entries in raw.items():
        if not isinstance(entries, list):
            continue
        for e in entries:
            out.append(Registry(
                jurisdiction=str(e.get("jurisdiction", "XX")),
                name=e["name"],
                category=category,
                scope=e.get("scope", ""),
                url=e.get("url", ""),
                access=e.get("access", "manual"),
                automatable=bool(e.get("automatable", False)),
                collector=e.get("collector", ""),
                auth_env=e.get("auth_env", ""),
                yields=tuple(e.get("yields", []) or []),
                licence=e.get("licence", ""),
                rate_limit=e.get("rate_limit", ""),
                notes=(e.get("notes") or "").strip(),
            ))
    return tuple(out)


def query(
    jurisdiction: str | None = None,
    category: str | None = None,
    yields: str | None = None,
    automatable: bool | None = None,
    implemented: bool | None = None,
) -> list[Registry]:
    out = list(load_catalog())
    if jurisdiction:
        j = jurisdiction.upper()
        out = [r for r in out if r.jurisdiction == j or r.jurisdiction.startswith(f"{j}-")
               or r.jurisdiction == "XX"]
    if category:
        out = [r for r in out if r.category == category]
    if yields:
        out = [r for r in out if any(yields.lower() in y.lower() for y in r.yields)]
    if automatable is not None:
        out = [r for r in out if r.automatable is automatable]
    if implemented is not None:
        out = [r for r in out if bool(r.collector) is implemented]
    return out


def coverage_report() -> str:
    """What the toolkit can and cannot reach. Honest by construction."""
    cat = load_catalog()
    lines = ["# Registry coverage", ""]
    total = len(cat)
    impl = sum(1 for r in cat if r.collector)
    auto = sum(1 for r in cat if r.automatable)
    lines += [
        f"- Catalogued: **{total}**",
        f"- Automatable: **{auto}**",
        f"- Implemented as collectors: **{impl}**",
        f"- Manual lookup only: **{total - auto}**",
        "",
        "Manual entries are catalogued deliberately. Knowing a registry exists "
        "and must be searched by hand is operationally useful; silently omitting "
        "it produces a false negative in the investigation.",
        "",
    ]
    for category in sorted({r.category for r in cat}):
        lines += [f"## {category.replace('_', ' ').title()}", "",
                  "| Jurisdiction | Registry | Access | Status | Yields |",
                  "|---|---|---|---|---|"]
        for r in sorted(query(category=category), key=lambda x: (x.jurisdiction, x.name)):
            lines.append(
                f"| {r.jurisdiction} | {r.name} | `{r.access}` | {r.status} | "
                f"{', '.join(r.yields[:4]) or '—'} |"
            )
        lines.append("")
    return "\n".join(lines)
