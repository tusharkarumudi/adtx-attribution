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
scraper-site.example/ads.txt
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
adtx portfolio scraper-site.example --index adtx.sqlite --registrants --out ./out
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
wanting a rival attributed to their scraper network simply plants the rival's IDs
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

### Not included: data brokers and people-search sites

Spokeo, BeenVerified, TruePeopleSearch, Radaris and equivalents are `DATA_BROKER`
in the source-class deny list and raise at collector load.

Three reasons, none of them squeamishness:

1. **They aren't public records.** They're commercial aggregations of purchased
   and scraped data with unmeasured error rates. A conclusion resting on one is
   hard to defend if the investigation ends up in front of a court.
2. **Their terms prohibit automated collection**, near-universally.
3. **Aggregating them into a dossier can make you a consumer reporting agency.**
   In the US, assembling personal information into a report used for employment,
   tenancy or credit decisions implicates FCRA regardless of intent; motor
   vehicle records implicate DPPA. This is a live exposure for investigative
   tooling, not a hypothetical.

If you're doing licensed investigative work that legitimately requires these, use
them through a vendor that carries the compliance obligations. Don't wire them
into an automated pivoting engine.

---

## Full collector list continued

¹ SEC fair-access policy requires a declared User-Agent and ≤10 req/s. Set
`contact_email` in your case file; the client builds the UA from it.

## Replacing paid APIs

| Instead of | Use | Trade-off |
|---|---|---|
| Paid WHOIS | RDAP | Strictly better — structured JSON, explicit redaction fields |
| Censys cert search | crt.sh + `tlsx` | Equivalent for SAN pivots |
| VirusTotal resolutions | mnemonic pdns + InternetDB | Better history than VT's free tier |
| OpenCorporates | GLEIF + EDGAR + Companies House | More calls, no cost, statutory sources |
| Paid sanctions screening | self-hosted yente | ~8 GB RAM; data licence needed for commercial use |
| Censys favicon index | local mmh3 + your corpus | They sell the *index*, not the hash. Worse day one, better once your corpus is scoped to your abuse population |

No open substitute exists for Farsight-depth historical passive DNS or bulk
historical WHOIS. Keep a paid line item for those two; drop the rest.

## Scope

Inherited from `attribution-graph` and enforced at runtime, not documented as
policy: a mandatory authorization reference, a hard pivot radius, entity-type
gating, and a source-class deny list that raises at collector load. See the
[core README](https://github.com/OWNER/attribution-graph#scope-is-executable-not-documentary).

This repository ships **no person-attribution collectors**. The `Collector`
protocol is documented and stable if you need them for an authorized
investigation; assembling them is deliberately left to you.

## Example case file

```yaml
case_ref: SCRAPE-2026-0417
authorization: "IR ticket SEC-88213 / preservation request 2026-08-02"
contact_email: "threatintel@example.com"
seeds:
  - domain:scraper-site.example
  - seller_id:pubmatic.com/156423
pivot_radius: 3
entity_types_allowed: [Company]
minimize: true
retention_days: 180
```

## Status

`0.1.0`, API unstable. `sellers.json` `is_confidential: 1` suppresses the entity
name — you still get `seller_type`, which tells you whether inventory is owned or
resold, and that alone reshapes a portfolio hypothesis. The EDGAR full-text
endpoint is undocumented and unversioned; the collector checks for fields rather
than assuming them, but pin a contract test if you depend on it.

## License

Apache-2.0.
