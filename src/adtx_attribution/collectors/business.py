"""Legal-entity collectors.

The ads.txt -> sellers.json chain is the strongest lever available for scraper,
MFA-site and ad-fraud attribution: monetization is the one thing an operator
cannot anonymize. To be paid, a real legal entity must be named to the ad system,
and sellers.json publishes that name, domain and often a contact address.
ads.txt 1.1's OWNERDOMAIN then ties a whole portfolio of sites back to one owner.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from datetime import datetime, timezone

from attribution_graph import Claim, Identifier, IdKind, Predicate, Reliability, SourceClass

from .base import Collector, register

# --------------------------------------------------------------------------- #
# ads.txt  (v1.1: OWNERDOMAIN / MANAGERDOMAIN)
# --------------------------------------------------------------------------- #

@register
class AdsTxtOwner(Collector):
    name = "ads_txt_owner"
    source_class = SourceClass.SELF_PUBLISHED
    accepts = (IdKind.DOMAIN,)
    priority = 2

    _VAR = re.compile(r"^\s*(OWNERDOMAIN|MANAGERDOMAIN)\s*=\s*([^\s#,]+)", re.I)

    async def collect(self, ident: Identifier) -> Iterable[Claim]:
        url = f"https://{ident.value}/ads.txt"
        r = await self.fetcher.get(url)
        if not r or r.status != 200 or not r.text:
            return []

        claims: list[Claim] = []
        group = f"ads_txt|{ident.value}"

        for line in r.text.splitlines():
            m = self._VAR.match(line)
            if m:
                var, val = m.group(1).upper(), m.group(2).lower()
                pred = (
                    Predicate.OWNER_DOMAIN if var == "OWNERDOMAIN"
                    else Predicate.MANAGER_DOMAIN
                )
                claims.append(self.claim(
                    ident, pred, Identifier(IdKind.DOMAIN, val), url,
                    reliability=Reliability.STRONG, correlation_group=group,
                ))
                continue

            # seller records: adsystem, seller_id, DIRECT|RESELLER [, cert_id]
            body = line.split("#", 1)[0].strip()
            if not body:
                continue
            parts = [p.strip() for p in body.split(",")]
            if len(parts) >= 3 and "." in parts[0]:
                adsystem, seller_id, rel = parts[0].lower(), parts[1], parts[2].upper()
                if rel not in ("DIRECT", "RESELLER"):
                    continue
                sid = Identifier(IdKind.SELLER_ID, f"{adsystem}/{seller_id}")
                claims.append(self.claim(
                    ident, Predicate.SELLER_OF, sid, url,
                    reliability=Reliability.STRONG,
                    correlation_group=group,
                    raw={"relationship": rel},
                ))
        return claims


# --------------------------------------------------------------------------- #
# sellers.json
# --------------------------------------------------------------------------- #

@register
class SellersJson(Collector):
    name = "sellers_json"
    source_class = SourceClass.SELF_PUBLISHED
    accepts = (IdKind.SELLER_ID,)
    priority = 1   # highest-selectivity business pivot available

    async def collect(self, ident: Identifier) -> Iterable[Claim]:
        try:
            adsystem, seller_id = ident.value.split("/", 1)
        except ValueError:
            return []

        url = f"https://{adsystem}/sellers.json"
        data = await self.fetcher.get_json(url)
        if not data:
            return []

        for s in data.get("sellers", []):
            if str(s.get("seller_id", "")).lower() != seller_id.lower():
                continue
            if int(s.get("is_confidential", 0)) == 1:
                # Publisher opted into confidentiality; type still tells us
                # whether the inventory is owned or resold.
                return [self.claim(
                    ident, Predicate.SELLER_OF, str(s.get("seller_type", "")).upper(), url,
                    reliability=Reliability.STRONG,
                    correlation_group=f"sellers_json|{adsystem}|{seller_id}",
                    raw={"is_confidential": 1},
                )]

            group = f"sellers_json|{adsystem}|{seller_id}"
            claims: list[Claim] = []
            if s.get("name"):
                claims.append(self.claim(
                    ident, Predicate.LEGAL_NAME,
                    Identifier(IdKind.ORG_NAME, s["name"]), url,
                    reliability=Reliability.STRONG, correlation_group=group,
                    raw={"seller_type": s.get("seller_type")},
                ))
            if s.get("domain"):
                claims.append(self.claim(
                    ident, Predicate.OPERATES,
                    Identifier(IdKind.DOMAIN, s["domain"]), url,
                    reliability=Reliability.STRONG, correlation_group=group,
                ))
            # Parent-object contact fields describe the ad system, not the
            # seller -- deliberately not emitted as seller evidence.
            return claims
        return []


# --------------------------------------------------------------------------- #
# GLEIF (LEI) -- free, no key, includes ownership tree
# --------------------------------------------------------------------------- #

@register
class Gleif(Collector):
    name = "gleif"
    source_class = SourceClass.PUBLIC_REGISTRY
    accepts = (IdKind.ORG_NAME, IdKind.LEI)
    priority = 2

    BASE = "https://api.gleif.org/api/v1"

    async def collect(self, ident: Identifier) -> Iterable[Claim]:
        if ident.kind is IdKind.LEI:
            url = f"{self.BASE}/lei-records/{ident.value}"
            data = await self.fetcher.get_json(url)
            records = [data["data"]] if data and "data" in data else []
        else:
            url = (
                f"{self.BASE}/lei-records?filter[entity.legalName]="
                f"{ident.value.replace(' ', '%20')}&page[size]=5"
            )
            data = await self.fetcher.get_json(url)
            records = (data or {}).get("data", [])

        claims: list[Claim] = []
        for rec in records:
            lei = rec.get("id")
            attrs = rec.get("attributes", {}).get("entity", {})
            lei_id = Identifier(IdKind.LEI, lei)
            group = f"gleif|{lei}"

            legal_name = (attrs.get("legalName") or {}).get("name")
            if legal_name:
                claims.append(self.claim(
                    lei_id, Predicate.LEGAL_NAME,
                    Identifier(IdKind.ORG_NAME, legal_name), url,
                    reliability=Reliability.AUTHORITATIVE, correlation_group=group,
                ))
            juris = attrs.get("jurisdiction")
            if juris:
                claims.append(self.claim(
                    lei_id, Predicate.INCORPORATED_IN, juris, url,
                    reliability=Reliability.AUTHORITATIVE, correlation_group=group,
                ))
            addr = attrs.get("legalAddress") or {}
            flat = ", ".join(
                filter(None, [
                    " ".join(addr.get("addressLines", []) or []),
                    addr.get("city"), addr.get("region"),
                    addr.get("postalCode"), addr.get("country"),
                ])
            )
            if flat:
                claims.append(self.claim(
                    lei_id, Predicate.REGISTERED_ADDRESS,
                    Identifier(IdKind.POSTAL_ADDRESS, flat), url,
                    reliability=Reliability.AUTHORITATIVE, correlation_group=group,
                ))
            reg = attrs.get("registeredAs")
            if reg and juris:
                claims.append(self.claim(
                    lei_id, Predicate.SAME_AS,
                    Identifier(IdKind.COMPANY_NUMBER, f"{juris}/{reg}"), url,
                    reliability=Reliability.AUTHORITATIVE, correlation_group=group,
                ))

            # ownership tree
            for rel in ("direct-parent", "ultimate-parent"):
                purl = f"{self.BASE}/lei-records/{lei}/{rel}"
                pdata = await self.fetcher.get_json(purl)
                pid = ((pdata or {}).get("data") or {}).get("id")
                if pid:
                    claims.append(self.claim(
                        Identifier(IdKind.LEI, pid), Predicate.PARENT_OF, lei_id, purl,
                        reliability=Reliability.AUTHORITATIVE,
                        correlation_group=f"gleif_rel|{lei}|{rel}",
                        raw={"relationship": rel},
                    ))
        return claims


# --------------------------------------------------------------------------- #
# SEC EDGAR -- free, no key, User-Agent required by fair-access policy
# --------------------------------------------------------------------------- #

@register
class SecEdgar(Collector):
    name = "sec_edgar"
    source_class = SourceClass.PUBLIC_REGISTRY
    accepts = (IdKind.ORG_NAME, IdKind.CIK)
    priority = 3

    FTS = "https://efts.sec.gov/LATEST/search-index"
    SUB = "https://data.sec.gov/submissions/CIK{cik}.json"

    async def collect(self, ident: Identifier) -> Iterable[Claim]:
        claims: list[Claim] = []
        ciks: list[str] = []

        if ident.kind is IdKind.CIK:
            ciks = [ident.value]
        else:
            q = ident.value.replace(" ", "+")
            url = f"{self.FTS}?q=%22{q}%22&forms=10-K,10-Q,8-K,S-1,20-F"
            data = await self.fetcher.get_json(url)
            hits = ((data or {}).get("hits") or {}).get("hits", [])
            for h in hits[:5]:
                for c in (h.get("_source", {}).get("ciks") or []):
                    ciks.append(str(c).zfill(10))
            ciks = list(dict.fromkeys(ciks))[:5]

        for cik in ciks:
            url = self.SUB.format(cik=cik.zfill(10))
            data = await self.fetcher.get_json(url)
            if not data:
                continue
            cik_id = Identifier(IdKind.CIK, cik)
            group = f"edgar|{cik}"

            if data.get("name"):
                claims.append(self.claim(
                    cik_id, Predicate.LEGAL_NAME,
                    Identifier(IdKind.ORG_NAME, data["name"]), url,
                    reliability=Reliability.AUTHORITATIVE, correlation_group=group,
                ))
            for former in data.get("formerNames", []) or []:
                if former.get("name"):
                    claims.append(self.claim(
                        cik_id, Predicate.LEGAL_NAME,
                        Identifier(IdKind.ORG_NAME, former["name"]), url,
                        reliability=Reliability.AUTHORITATIVE,
                        correlation_group=group,
                        observed_at=_parse_iso(former.get("to")),
                        raw={"former": True},
                    ))
            if data.get("stateOfIncorporation"):
                claims.append(self.claim(
                    cik_id, Predicate.INCORPORATED_IN,
                    f"US-{data['stateOfIncorporation']}", url,
                    reliability=Reliability.AUTHORITATIVE, correlation_group=group,
                ))
            addrs = data.get("addresses", {}) or {}
            biz = addrs.get("business") or {}
            flat = ", ".join(filter(None, [
                biz.get("street1"), biz.get("street2"), biz.get("city"),
                biz.get("stateOrCountry"), biz.get("zipCode"),
            ]))
            if flat:
                claims.append(self.claim(
                    cik_id, Predicate.REGISTERED_ADDRESS,
                    Identifier(IdKind.POSTAL_ADDRESS, flat), url,
                    reliability=Reliability.AUTHORITATIVE, correlation_group=group,
                ))
            for site in (data.get("website"), data.get("investorWebsite")):
                if site:
                    dom = re.sub(r"^https?://(www\.)?", "", site).split("/")[0].lower()
                    claims.append(self.claim(
                        cik_id, Predicate.OPERATES,
                        Identifier(IdKind.DOMAIN, dom), url,
                        reliability=Reliability.AUTHORITATIVE, correlation_group=group,
                    ))
        return claims


# --------------------------------------------------------------------------- #
# Imprint / legal notice scraping (EU §5 TMG, DSA trader disclosure)
# --------------------------------------------------------------------------- #

@register
class Imprint(Collector):
    name = "imprint"
    source_class = SourceClass.SELF_PUBLISHED
    accepts = (IdKind.DOMAIN,)
    priority = 3

    PATHS = (
        "/impressum", "/imprint", "/legal", "/legal-notice", "/terms",
        "/terms-of-service", "/privacy", "/privacy-policy", "/about", "/contact",
    )

    # Legal-form tokens across the jurisdictions most common in scraper hosting.
    ENTITY_RE = re.compile(
        r"([A-Z][\w&.,'’\-]*(?:\s+[A-Z0-9][\w&.,'’\-]*){0,5}\s+"
        r"(?:GmbH(?:\s*&\s*Co\.?\s*KG)?|UG(?:\s*\(haftungsbeschränkt\))?|AG|"
        r"S\.?A\.?R\.?L\.?|B\.?V\.?|N\.?V\.?|s\.?r\.?o\.?|Sp\.?\s*z\s*o\.?o\.?|"
        r"Ltd\.?|Limited|LLC|L\.?L\.?C\.?|Inc\.?|Corp\.?|LLP|PLC|Pte\.?\s*Ltd\.?|"
        r"Pvt\.?\s*Ltd\.?|OÜ|AB|ApS|Oy|SIA|d\.?o\.?o\.?))"
    )
    REGNUM_RE = re.compile(
        r"(?:HRB|HRA|CHE-|VAT(?:\s*ID)?[:\s]|USt-IdNr\.?[:\s]|Company\s*(?:No\.?|Number)[:\s]|"
        r"CIN[:\s]|GSTIN[:\s])\s*([A-Z0-9\-/. ]{5,25})",
        re.I,
    )
    EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")

    async def collect(self, ident: Identifier) -> Iterable[Claim]:
        claims: list[Claim] = []
        for path in self.PATHS:
            url = f"https://{ident.value}{path}"
            r = await self.fetcher.get(url, allow_html=True)
            if not r or r.status != 200 or len(r.text) < 200:
                continue
            text = re.sub(r"<[^>]+>", " ", r.text)
            text = re.sub(r"\s+", " ", text)[:40_000]
            group = f"imprint|{ident.value}|{path}"

            for m in dict.fromkeys(self.ENTITY_RE.findall(text)):
                claims.append(self.claim(
                    ident, Predicate.LEGAL_NAME,
                    Identifier(IdKind.ORG_NAME, m.strip()), url,
                    reliability=Reliability.MODERATE, correlation_group=group,
                ))
            for m in dict.fromkeys(self.REGNUM_RE.findall(text)):
                claims.append(self.claim(
                    ident, Predicate.SAME_AS,
                    Identifier(IdKind.COMPANY_NUMBER, f"unknown/{m.strip()}"), url,
                    reliability=Reliability.MODERATE, correlation_group=group,
                ))
            for m in dict.fromkeys(self.EMAIL_RE.findall(text)):
                claims.append(self.claim(
                    ident, Predicate.PROFILE_BINDING,
                    Identifier(IdKind.EMAIL, m), url,
                    reliability=Reliability.MODERATE, correlation_group=group,
                ))
            if claims:
                break   # first page that yields structure wins; stop hammering
        return claims


# --------------------------------------------------------------------------- #
# UK Companies House (free key) -- officers + PSC beneficial ownership
# --------------------------------------------------------------------------- #

@register
class CompaniesHouseUK(Collector):
    name = "companies_house_uk"
    source_class = SourceClass.PUBLIC_REGISTRY
    accepts = (IdKind.ORG_NAME, IdKind.COMPANY_NUMBER)
    needs_key = "CH_API_KEY"
    priority = 3

    BASE = "https://api.company-information.service.gov.uk"

    async def collect(self, ident: Identifier) -> Iterable[Claim]:
        import base64
        key = os.environ.get(self.needs_key or "")
        if not key:
            return []
        auth = base64.b64encode(f"{key}:".encode()).decode()
        hdr = {"Authorization": f"Basic {auth}"}

        if ident.kind is IdKind.COMPANY_NUMBER:
            juris, num = (ident.value.split("/", 1) + [""])[:2]
            if juris not in ("gb", "uk", "unknown"):
                return []
            numbers = [num]
        else:
            url = f"{self.BASE}/search/companies?q={ident.value.replace(' ', '+')}&items_per_page=5"
            data = await self.fetcher.get_json(url, headers=hdr)
            numbers = [i["company_number"] for i in (data or {}).get("items", [])]

        claims: list[Claim] = []
        for num in numbers[:5]:
            cn = Identifier(IdKind.COMPANY_NUMBER, f"gb/{num}")
            group = f"ch_uk|{num}"

            purl = f"{self.BASE}/company/{num}/persons-with-significant-control"
            pdata = await self.fetcher.get_json(purl, headers=hdr)
            for it in (pdata or {}).get("items", []):
                nm = it.get("name")
                if not nm:
                    continue
                kind = it.get("kind", "")
                is_person = "individual" in kind
                claims.append(self.claim(
                    Identifier(
                        IdKind.PERSON_NAME if is_person else IdKind.ORG_NAME, nm
                    ),
                    Predicate.BENEFICIAL_OWNER_OF, cn, purl,
                    reliability=Reliability.AUTHORITATIVE,
                    correlation_group=group,
                    observed_at=_parse_iso(it.get("notified_on")),
                    raw={"natures_of_control": it.get("natures_of_control")},
                ))

            ourl = f"{self.BASE}/company/{num}/officers"
            odata = await self.fetcher.get_json(ourl, headers=hdr)
            for it in (odata or {}).get("items", []):
                nm = it.get("name")
                if not nm or it.get("resigned_on"):
                    continue
                claims.append(self.claim(
                    Identifier(IdKind.PERSON_NAME, nm),
                    Predicate.OFFICER_OF, cn, ourl,
                    reliability=Reliability.AUTHORITATIVE,
                    correlation_group=group,
                    observed_at=_parse_iso(it.get("appointed_on")),
                    raw={"role": it.get("officer_role")},
                ))
        return claims


# --------------------------------------------------------------------------- #
# Self-hosted yente (OpenSanctions + OffshoreLeaks + GLEIF as FollowTheMoney)
# --------------------------------------------------------------------------- #

@register
class Yente(Collector):
    name = "opensanctions_yente"
    source_class = SourceClass.OPEN_DATASET
    accepts = (IdKind.ORG_NAME, IdKind.PERSON_NAME)
    priority = 4

    async def collect(self, ident: Identifier) -> Iterable[Claim]:
        base = os.environ.get("YENTE_URL", "http://localhost:8000")
        schema = "Company" if ident.kind is IdKind.ORG_NAME else "Person"
        url = (
            f"{base}/search/default?q={ident.value.replace(' ', '%20')}"
            f"&schema={schema}&limit=5"
        )
        data = await self.fetcher.get_json(url)
        claims: list[Claim] = []
        for res in (data or {}).get("results", []):
            props = res.get("properties", {})
            score = float(res.get("score", 0) or 0)
            if score < 0.7:
                continue
            group = f"yente|{res.get('id')}"
            for alias in (props.get("name", []) + props.get("alias", []))[:5]:
                claims.append(self.claim(
                    ident, Predicate.SAME_AS,
                    Identifier(ident.kind, alias), url,
                    reliability=Reliability.MODERATE, correlation_group=group,
                    raw={"yente_score": score, "datasets": res.get("datasets")},
                ))
            for lei in props.get("leiCode", [])[:2]:
                claims.append(self.claim(
                    ident, Predicate.SAME_AS,
                    Identifier(IdKind.LEI, lei), url,
                    reliability=Reliability.STRONG, correlation_group=group,
                ))
        return claims


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
