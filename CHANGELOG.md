# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-08-17

Initial public release.

### Added
- Collectors: ads.txt v1.1 (OWNERDOMAIN/MANAGERDOMAIN), sellers.json, GLEIF,
  SEC EDGAR, UK Companies House, imprint/legal-notice scraping, self-hosted yente
- Infrastructure collectors: RDAP, crt.sh, InternetDB, mnemonic passive DNS,
  local favicon mmh3
- Reverse ads.txt/sellers.json index (`adtx-index`) providing seller-ID and
  OWNERDOMAIN portfolio lookups
- The index satisfies `SelectivityIndex`, supplying corpus-backed evidence
  weights instead of per-case upper bounds
- `adtx run` CLI with corpus wiring and a warning when run without one

### Added (0.2.0)
- Registry catalog: 30 corporate, land and IP registries across ~20 jurisdictions,
  with automatability marked and `adtx registries` for querying it
- Collectors: OpenCorporates, USPTO trademark, GitHub/GitLab organizations,
  npm/PyPI/crates.io publisher provenance
- Land records: NYC ACRIS and HM Land Registry overseas-company data, entity-keyed
  by construction with natural-person owners suppressed to a terminal marker

### Added (0.3.0)
- Person-scoped collectors folded in as the `persona` extra: Gravatar, GitHub
  commit intel, PGP keyservers, holehe, WhatsMyName username expansion
- Three-key opt-in: entity_types_allowed, per-collector persona_collectors
  allowlist, and a separate allow_username_enumeration flag for enumeration
- Gated collectors are audit-logged rather than silently skipped
- `examples/end_to_end_domain.py` — full offline chain with interpretation
- `examples/reference_collector.py` — documented protocol template

### Known limitations
- `is_confidential: 1` sellers expose only `seller_type`, not entity name
- EDGAR full-text endpoint is undocumented and unversioned
- Imprint parsing is regex-based over stripped HTML; treat as MODERATE evidence
