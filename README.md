# adtx-attribution

[![CI](https://github.com/OWNER/adtx-attribution/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/adtx-attribution/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/adtx-attribution.svg)](https://pypi.org/project/adtx-attribution/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**Attribute websites to the legal entities that get paid for them.**

Collectors for [attribution-graph](https://github.com/OWNER/attribution-graph),
built around one observation: an operator can hide registrant, hosting, DNS and
email — but to be paid, a real legal entity has to be named to an ad system, and
the IAB's `sellers.json` standard publishes that name.

```bash
pip install adtx-attribution
```

## The chain

```
site.example/ads.txt
  └─ pubmatic.com, 156423, DIRECT
      └─ pubmatic.com/sellers.json
          └─ { seller_id: 156423, name: "Example Media Holdings Ltd",
               domain: "examplemedia.example", seller_type: PUBLISHER }
              ├─ GLEIF          → LEI, registered address, parent/child ownership tree
              ├─ SEC EDGAR      → CIK, officers, former names
              ├─ Companies House→ directors, PSC beneficial owners
              └─ RDAP / crt.sh  → back to infrastructure
```

Every hop is free, keyless, and either statutory or self-published. No paid API
in the critical path.

## Reverse index: the pivot that isn't public

A forward lookup tells you how one site monetizes. The pivot that matters is the
reverse — **seller ID → every site declaring it** — which is the operator's
portfolio. No free API exposes that automatably, so build it:

```bash
adtx-index build   --domains tranco-top-1m.txt --db adtx.sqlite   # crawl ads.txt
adtx-index sellers --db adtx.sqlite                               # crawl sellers.json
adtx-index lookup  --db adtx.sqlite --seller pubmatic.com/156423  # portfolio
adtx-index lookup  --db adtx.sqlite --owner examplemedia.example  # OWNERDOMAIN map
```

`ads.txt` v1.1 added `OWNERDOMAIN` and `MANAGERDOMAIN`, which operators populate
voluntarily because DSPs penalize their absence. For a network monetizing across
dozens of domains, that's a self-published portfolio map.

## The index is also your selectivity corpus

This matters more than the reverse lookup. `attribution-graph` derives evidence
weight from how many entities carry an identifier — but a per-case index can only
count what the case has seen, so it treats a seller ID held by four thousand
sites as unique and reports inflated confidence.

```bash
adtx run --case case.yaml --index adtx.sqlite --out ./out
```

Without `--index` the CLI warns you, and it means it: **confidence figures from a
run with no corpus are upper bounds, not assessments.**

## Portfolio expansion

One seed domain to an actor's whole estate, then back through time for a lead:

```bash
adtx portfolio site.example --index adtx.sqlite --registrants --out ./out
```

The chain:

```
seed domain
  ├─ live publisher IDs      (AdSense ca-pub, GA4, UA, GTM, Pixel, Sentry, Yandex…)
  ├─ archived publisher IDs  (Wayback CDX, sampled across the timeline)
  ├─ ads.txt seller IDs      (live + archived)
  │
  └─> reverse index → every domain sharing any of them
        └─> sellers.json → legal entity paid for each
              └─> RDAP now + archived contact pages then
```

**Why the archive is the valuable half.** Attribution hygiene improves over time.
A network running today behind privacy proxies, split analytics accounts and a
clean ads.txt was frequently sloppy in 2019 — one AdSense ID across the whole
portfolio, a real registrant in WHOIS, a contact page with a named person. The
operator cleaned up; the archive didn't. An ID observed in 2019 is still a valid
link to the domain today, and the scoring model decays it by age rather than
discarding it or pretending it's current.

Pre-2018 observations are flagged separately in the output. GDPR-era WHOIS
redaction started that year, so anything older is frequently the only
non-proxied identity in the entire portfolio.

**Selectivity is the brake.** A GTM container on four sites is a portfolio; the
same pivot on forty thousand sites is a page template. The only thing
distinguishing them is the holder count, so expansion is gated on measured
selectivity rather than a hop limit. Rejected pivots are reported with their
holder count, not silently dropped:

```
pivots rejected as non-discriminating:
  gtm:GTM-K3F9L2  — 38,412 holders — platform artifact, not a portfolio
```

## Planted-identifier detection

The gap nobody accounts for: **high-selectivity identifiers are also
high-forgeability identifiers.**

The scoring model weights a shared AdSense publisher ID at ~14 nats precisely
because so few sites carry it. But pasting a competitor's `ca-pub-` string into
your page source costs nothing and needs no access to their account. Anyone
wanting a rival attributed to their  network simply plants the rival's IDs
across it — and every selectivity-based system, unguarded, hands them the result.

`adversarial.py` runs four checks:

| Check | Question |
|---|---|
| Reciprocity | Does `sellers.json` name this domain back? Requires control of *both* sides. |
| Load-bearing | Is the loader actually present, or is the ID inert text in a comment? |
| Temporal depth | Does it have archived history, or did it appear all at once? |
| Asymmetry | Is a tiny site carrying a major property's ID? Template reuse, not common control. |

Failures **demote, never delete**. A planted identifier is still evidence — of
someone attempting to manufacture an attribution — and deleting it hides the most
interesting fact in the case.

Any finding resting on a shared analytics ID should go through this before it is
reported.

## Ingest from SpiderFoot and OpenCTI

Don't out-collect SpiderFoot — consume it. It has a decade of module development
and 200+ sources; what it doesn't do is decide what its correlations are worth.

```python
from adtx_attribution import from_spiderfoot_db, from_opencti_bundle
claims = from_spiderfoot_db("spiderfoot.db", scan_id="abc123")
claims += from_opencti_bundle("bundle.json")
```

The adapters do the part that can't be automated generically: assigning
correlation groups by what actually constitutes one observation in the source
system. A SpiderFoot module emitting 200 events queried one API once — that's one
group. An OpenCTI report asserting 40 relationships is one source, not 40.
Analyst-entered OpenCTI confidence caps at STRONG, never AUTHORITATIVE; a human
typing 100 is not a registry assertion. Unknown event types are skipped rather
than guessed, since a wrong identifier kind produces a wrong selectivity lookup
and therefore a wrong score.

## Ingest from Robin (dark web OSINT)

[Robin](https://github.com/apurvsinghgautam/robin) searches dark web engines over
Tor and summarises findings with an LLM. It is a strong collector; this adapter
turns its output into scored claims.

```python
from adtx_attribution import from_robin, to_handle_observations
claims = from_robin("investigations/kraken.json")
rows = to_handle_observations(claims, case_ref="CASE-1")   # -> handle-correlation
```

Extracts PGP fingerprints, .onion addresses, Session/Tox/Jabber IDs, wallet
addresses and contextual handles, then hands the handles to
`handle-correlation` with their page-level durable identifiers attached — which
is what lets a shared PGP key lift two forum accounts above the correlation-point
floor.

Three constraints the adapter enforces, each for a specific reason:

**One page is one correlation group.** A Robin query returns N results from one
engine. Those are one query against one index, not N confirmations.

**LLM output is capped at UNCERTAIN.** A model concluding two handles are one
actor is inference over text, not observation. It can corroborate a link with
independent support; it cannot create one. The whole summary is one group.

**Claims are marked `text_is_derived`.** Robin truncates scraped text to 2,000
characters and discards the response body — sensible for an LLM context window,
fatal for a chain of custody. And `.onion` content has no Wayback and no CT, so
what was not captured at the time is gone. These claims are leads, and the
evidence manifest says so rather than implying a capture that does not exist.

## Registry catalog

Most corporate and land registries in the world cannot be automated — captcha,
session, paid-per-search, or robots-disallowed. A catalog that omits those is
worse than useless mid-investigation, because you conclude no source exists when
one does. So all 30 are catalogued and the un-automatable ones are marked:

```bash
adtx registries --jurisdiction IN            # what exists for India
adtx registries --yields beneficial_owner    # who publishes BO data
adtx registries --coverage                   # full report
```

Covers GLEIF, OpenCorporates, EDGAR, Companies House, MCA21, BRIS,
Handelsregister, INPI, KVK, ACRA, ASIC, NZ Companies Office, ICIJ Offshore Leaks,
Open Ownership, and land/IP registries. 18 automatable, 9 implemented.

## Collectors

| Name | Source | Auth | Emits |
|---|---|---|---|
| `ads_txt_owner` | `/ads.txt` v1.1 | none | seller IDs, `OWNERDOMAIN`, `MANAGERDOMAIN` |
| `sellers_json` | `{adsystem}/sellers.json` | none | legal entity name, domain, seller type |
| `gleif` | GLEIF LEI API v1 | none | legal name, address, jurisdiction, ownership tree |
| `sec_edgar` | `efts.sec.gov` + `data.sec.gov` | none¹ | CIK, former names, addresses, websites |
| `companies_house_uk` | UK Companies House | free key | officers, PSC beneficial owners |
| `imprint` | `/impressum`, `/legal`, `/terms` | none | EU §5 TMG / DSA legal-entity disclosure |
| `opensanctions_yente` | self-hosted yente | none | sanctions, PEP, OffshoreLeaks, fuzzy names |
| `rdap` | IANA RDAP bootstrap | none | registrant, admin, tech contacts |
| `crtsh` | Certificate Transparency | none | SAN pivots |
| `internetdb` | `internetdb.shodan.io` | none | hostnames per IP |
| `mnemonic_pdns` | mnemonic passive DNS v3 | none | historical resolutions |
| `favicon_mmh3` | local mmh3 | none | favicon hashes |
| `opencorporates` | OpenCorporates v0.4 | key | 140M+ companies, officers, former names |
| `uspto_trademark` | USPTO Open Data | free key | brand → owning entity + address |
| `code_host_org` | GitHub/GitLab orgs | free token | org → domain, email, location |
| `package_registry` | npm, PyPI, crates.io | none | publisher-declared maintainer bindings |
| `nyc_acris` | NYC ACRIS (Socrata) | none | property parties (entity-keyed) |
| `uk_overseas_property` | HM Land Registry OCOD | bulk | UK titles held by overseas companies |
| `analytics_ids` | live page source | none | AdSense, GA4, UA, GTM, Pixel, Sentry, Yandex, Clarity, Hotjar |
| `wayback` | Internet Archive CDX | none | historical IDs, historical ads.txt, pre-redaction contacts |

### Land records are entity-keyed

`records.py` accepts an owning legal entity and returns its parcels. It **raises**
if handed a natural-person name.

The reason is narrow, not squeamish. Keyed on a company, a property record
answers "what does this shell own" — the question in asset tracing, sanctions
work and real-estate fraud. Keyed on a person's name, the identical API call
returns their home address. Same dataset, different artifact, and the second has
no investigative use the first doesn't already serve.

When a parcel's owner of record *is* a natural person, that's analytically
meaningful — the ownership chain terminates rather than continuing into another
shell. The collector emits `chain_terminates_natural_person` and suppresses the
name and address. The signal survives; the dossier doesn't.

Name classification is deliberately conservative: an unmatched name is treated as
a person. A false negative costs one lead. A false positive publishes a home
address.

### Person-scoped collectors: opt-in, three keys

Gravatar, GitHub commit-email mining, PGP keyservers, holehe and WhatsMyName
username expansion ship in the `persona` extra:

```bash
pip install "adtx-attribution[persona]"
```

**Installing does not enable them.** Two gates must both be open, and
enumeration needs a third:

```yaml
entity_types_allowed: [Company, Persona]      # key 1
persona_collectors: [gravatar, github_intel]  # key 2 — per collector
allow_username_enumeration: false             # key 3 — enumeration only
```

Two keys rather than one is deliberate. A case scoped to `Company` cannot start
enumerating people because someone passed `--collectors all`, and enabling one
persona collector does not enable the rest. Gated collectors are written to the
audit log rather than silently skipped, so a reviewer can see which sources were
available and deliberately unused.

`username_expand` takes a third key because it differs in kind. The others take
an identifier you already hold and query one named service; enumeration takes a
bare handle and sweeps hundreds of sites. By the scoring model's own logic its
output is worth very little — every hit joins one correlation group, so five
hundred matches score the same as one — which is a reason to think carefully
before turning it on, not a reason it is unavailable.

`pivot_radius` still applies. It is what stops an investigation of a 
network from walking into the personal life of someone who once committed to a
shared repository.


## Worked examples

```bash
python examples/end_to_end_domain.py     # full chain, offline, deterministic
python examples/reference_collector.py   # template for writing your own
```

`handle-correlation` ships `examples/end_to_end_handles.py` for the persona side.

`end_to_end_domain.py` runs the complete chain against synthetic data and prints
the resolved entities, assessments, blocked merges, expectation checklist and
every output file. It closes with an interpretation section explaining why the
company resolves confidently while the domain-to-company link stays a lead —
which is the behaviour to understand before trusting anything this produces.

`reference_collector.py` is a documented template. The comments explain what
each protocol decision costs you if you get it wrong, especially
`correlation_group`, which is the field that determines whether your collector
produces calibrated scores or confident wrong answers.

## Full collector list continued

¹ SEC fair-access policy requires a declared User-Agent and ≤10 req/s. Set
`contact_email` in your case file; the client builds the UA from it.

## Scope

Inherited from `attribution-graph` and enforced at runtime, not documented as
policy: a mandatory authorization reference, a hard pivot radius, entity-type
gating, and a source-class deny list that raises at collector load. See the
[core README](https://github.com/OWNER/attribution-graph#scope-is-executable-not-documentary).

## Example case file

```yaml
case_ref: SCRAPE-2026-0417
authorization: "IR ticket SEC-88213 / preservation request 2026-08-02"
contact_email: "threatintel@example.com"
seeds:
  - domain:site.example
  - seller_id:pubmatic.com/156423
pivot_radius: 3
entity_types_allowed: [Company]
minimize: true
retention_days: 180
```

## License

Apache-2.0.
