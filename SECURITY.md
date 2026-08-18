# Security policy

## Reporting a vulnerability

Report privately via GitHub Security Advisories ("Report a vulnerability" on the
Security tab). Please do not open a public issue for security matters.

Expect an acknowledgement within 5 working days.

## Scope

In scope:

- Code execution via crafted ads.txt, sellers.json or registry API responses
- SQL injection in the corpus index
- SSRF via crafted domain or ad-system values reaching the fetcher
- Cache poisoning in the on-disk response cache
- Bypass of the source-class deny list

Out of scope:

- Misuse of the library for investigations the operator was not authorized to
  conduct. Scope enforcement here is a guardrail against accident and drift, not
  a security boundary against a determined operator who controls the code.
- Vulnerabilities in `attribution-graph` — report those to that repository.

## Design note

`AttributionGraph` and `Claim` objects deserialized from untrusted JSON should
be treated as untrusted input. The library does not currently sandbox claim
`raw` payloads.
