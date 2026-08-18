"""Reverse ads.txt / sellers.json index.

Solves two problems with one artifact.

**Portfolio discovery.** A forward lookup (domain -> seller_id) tells you how one
site monetizes. The pivot that matters for network attribution is the reverse --
seller_id -> every site declaring it -- which reveals the operator's portfolio.
That requires an index, because no public API exposes it in a form that is both
free and automatable.

**Selectivity.** The scoring model's evidence weight comes from how many entities
carry an identifier value. Without a corpus, a per-case index cannot tell a
seller ID held by one site from one held by four thousand, and treats both as
unique. This index supplies the real counts, which is the difference between an
upper bound on confidence and an actual assessment.

Build it once from a domain corpus (Tranco, a CT-derived host list, or your own
abuse population), refresh weekly, and pass it to the engine as the selectivity
index.

    python -m adtx_attribution.index build --domains domains.txt --db adtx.sqlite
    python -m adtx_attribution.index sellers --db adtx.sqlite --refresh
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from attribution_graph import Identifier, IdKind

from .net import Fetcher

SCHEMA = """
CREATE TABLE IF NOT EXISTS ads_record (
    domain      TEXT NOT NULL,
    adsystem    TEXT NOT NULL,
    seller_id   TEXT NOT NULL,
    relationship TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (domain, adsystem, seller_id)
);
CREATE INDEX IF NOT EXISTS ix_ads_seller ON ads_record (adsystem, seller_id);

CREATE TABLE IF NOT EXISTS ads_var (
    domain     TEXT NOT NULL,
    variable   TEXT NOT NULL,
    value      TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (domain, variable, value)
);
CREATE INDEX IF NOT EXISTS ix_ads_var_value ON ads_var (variable, value);

CREATE TABLE IF NOT EXISTS seller (
    adsystem        TEXT NOT NULL,
    seller_id       TEXT NOT NULL,
    name            TEXT,
    domain          TEXT,
    seller_type     TEXT,
    is_confidential INTEGER DEFAULT 0,
    fetched_at      TEXT NOT NULL,
    PRIMARY KEY (adsystem, seller_id)
);
CREATE INDEX IF NOT EXISTS ix_seller_name   ON seller (name);
CREATE INDEX IF NOT EXISTS ix_seller_domain ON seller (domain);

CREATE TABLE IF NOT EXISTS analytics_id (
    domain     TEXT NOT NULL,
    scheme     TEXT NOT NULL,
    value      TEXT NOT NULL,
    first_seen TEXT,
    historical INTEGER DEFAULT 0,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (domain, scheme, value)
);
CREATE INDEX IF NOT EXISTS ix_analytics_val ON analytics_id (scheme, value);

CREATE TABLE IF NOT EXISTS corpus_meta (key TEXT PRIMARY KEY, value TEXT);
"""

_VAR = re.compile(r"^\s*(OWNERDOMAIN|MANAGERDOMAIN|INVENTORYPARTNERDOMAIN)\s*=\s*([^\s#,]+)", re.I)


@dataclass
class AdsTxtIndex:
    """Persistent corpus index. Satisfies ``SelectivityIndex``."""

    db_path: str

    def __post_init__(self) -> None:
        self.conn = sqlite3.connect(self.db_path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---- SelectivityIndex protocol ---------------------------------------- #

    def holders(self, ident: Identifier) -> int:
        """Distinct domains observed carrying this identifier value."""
        cur = self.conn.cursor()
        if ident.kind is IdKind.SELLER_ID:
            try:
                adsystem, sid = ident.value.split("/", 1)
            except ValueError:
                return 0
            cur.execute(
                "SELECT COUNT(DISTINCT domain) FROM ads_record "
                "WHERE adsystem = ? AND seller_id = ?",
                (adsystem, sid),
            )
        elif ident.kind is IdKind.ANALYTICS_ID:
            scheme, _, val = ident.value.partition(":")
            cur.execute(
                "SELECT COUNT(DISTINCT domain) FROM analytics_id "
                "WHERE scheme = ? AND value = ?", (scheme, val))
        elif ident.kind is IdKind.ORG_NAME:
            cur.execute(
                "SELECT COUNT(*) FROM seller WHERE name = ? COLLATE NOCASE", (ident.value,)
            )
        elif ident.kind is IdKind.DOMAIN:
            cur.execute(
                "SELECT (SELECT COUNT(DISTINCT domain) FROM ads_var "
                " WHERE variable = 'OWNERDOMAIN' AND value = ?) + "
                "(SELECT COUNT(*) FROM seller WHERE domain = ?)",
                (ident.value, ident.value),
            )
        else:
            return 0
        row = cur.fetchone()
        return int(row[0]) if row and row[0] else 0

    def domains_for_analytics(self, scheme: str, value: str) -> list[str]:
        """Reverse pivot: every domain observed with this publisher ID.

        Includes historical observations. A shared AdSense ID from 2019 is
        evidence of common control even if both sites have separate accounts
        today -- the scoring model decays it by age rather than discarding it.
        """
        cur = self.conn.cursor()
        cur.execute(
            "SELECT DISTINCT domain FROM analytics_id WHERE scheme = ? AND value = ? "
            "ORDER BY domain", (scheme, value))
        return [r[0] for r in cur.fetchall()]

    def holders_analytics(self, scheme: str, value: str) -> int:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT COUNT(DISTINCT domain) FROM analytics_id WHERE scheme = ? AND value = ?",
            (scheme, value))
        return int(cur.fetchone()[0] or 0)

    def sellers_for_domain(self, domain: str) -> list[tuple[str, str]]:
        cur = self.conn.cursor()
        cur.execute("SELECT adsystem, seller_id FROM ads_record WHERE domain = ?",
                    (domain.lower(),))
        return cur.fetchall()

    def owner_domains_for(self, domain: str) -> list[str]:
        cur = self.conn.cursor()
        cur.execute("SELECT value FROM ads_var WHERE domain = ? AND variable = 'OWNERDOMAIN'",
                    (domain.lower(),))
        return [r[0] for r in cur.fetchall()]

    def record_analytics(self, domain: str, scheme: str, value: str,
                         first_seen=None, historical: bool = False) -> None:
        from datetime import datetime, timezone
        self.conn.execute(
            "INSERT OR IGNORE INTO analytics_id VALUES (?,?,?,?,?,?)",
            (domain.lower(), scheme, value,
             first_seen.isoformat() if first_seen else None,
             int(historical), datetime.now(timezone.utc).isoformat()))
        self.conn.commit()

    def universe(self) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(DISTINCT domain) FROM ads_record")
        n = int(cur.fetchone()[0] or 0)
        return max(n, 1000)

    # ---- reverse lookups --------------------------------------------------- #

    def sites_for_seller(self, adsystem: str, seller_id: str) -> list[str]:
        """The portfolio pivot: every site declaring this seller ID."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT domain FROM ads_record WHERE adsystem = ? AND seller_id = ? "
            "ORDER BY domain",
            (adsystem.lower(), seller_id),
        )
        return [r[0] for r in cur.fetchall()]

    def sites_for_owner(self, owner_domain: str) -> list[str]:
        """Sites declaring OWNERDOMAIN = this domain -- a self-published
        portfolio map, published because DSPs penalize its absence."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT domain FROM ads_var WHERE variable = 'OWNERDOMAIN' "
            "AND value = ? ORDER BY domain",
            (owner_domain.lower(),),
        )
        return [r[0] for r in cur.fetchall()]

    def sellers_for_name(self, name: str) -> list[tuple[str, str, str]]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT adsystem, seller_id, domain FROM seller "
            "WHERE name = ? COLLATE NOCASE",
            (name,),
        )
        return cur.fetchall()

    def ad_systems(self) -> list[str]:
        cur = self.conn.cursor()
        cur.execute("SELECT DISTINCT adsystem FROM ads_record ORDER BY adsystem")
        return [r[0] for r in cur.fetchall()]

    def stats(self) -> dict:
        cur = self.conn.cursor()
        out = {}
        for label, q in (
            ("domains", "SELECT COUNT(DISTINCT domain) FROM ads_record"),
            ("ads_records", "SELECT COUNT(*) FROM ads_record"),
            ("ad_systems", "SELECT COUNT(DISTINCT adsystem) FROM ads_record"),
            ("sellers", "SELECT COUNT(*) FROM seller"),
            ("named_sellers", "SELECT COUNT(*) FROM seller WHERE name IS NOT NULL"),
            ("owner_declarations",
             "SELECT COUNT(*) FROM ads_var WHERE variable = 'OWNERDOMAIN'"),
            ("analytics_ids", "SELECT COUNT(DISTINCT scheme || value) FROM analytics_id"),
            ("analytics_observations", "SELECT COUNT(*) FROM analytics_id"),
        ):
            cur.execute(q)
            out[label] = int(cur.fetchone()[0] or 0)
        return out


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #

async def crawl_ads_txt(index: AdsTxtIndex, domains: list[str], concurrency: int = 20) -> int:
    from datetime import datetime, timezone

    fetcher = Fetcher(user_agent="adtx-attribution/0.1 (+https://github.com/OWNER/adtx-attribution)",
                      max_requests=len(domains) * 2 + 100)
    sem = asyncio.Semaphore(concurrency)
    now = datetime.now(timezone.utc).isoformat()
    rows_a: list[tuple] = []
    rows_v: list[tuple] = []

    async def one(domain: str) -> None:
        async with sem:
            r = await fetcher.get(f"https://{domain}/ads.txt", allow_html=True)
            if not r or r.status != 200 or not r.text:
                return
            for line in r.text.splitlines()[:5000]:
                m = _VAR.match(line)
                if m:
                    rows_v.append((domain, m.group(1).upper(), m.group(2).lower(), now))
                    continue
                body = line.split("#", 1)[0].strip()
                if not body:
                    continue
                parts = [p.strip() for p in body.split(",")]
                if len(parts) >= 3 and "." in parts[0]:
                    rel = parts[2].upper()
                    if rel in ("DIRECT", "RESELLER"):
                        rows_a.append((domain, parts[0].lower(), parts[1], rel, now))

    await asyncio.gather(*(one(d) for d in domains))
    await fetcher.aclose()

    index.conn.executemany(
        "INSERT OR REPLACE INTO ads_record VALUES (?,?,?,?,?)", rows_a)
    index.conn.executemany(
        "INSERT OR REPLACE INTO ads_var VALUES (?,?,?,?)", rows_v)
    index.conn.commit()
    return len(rows_a)


async def crawl_sellers_json(index: AdsTxtIndex, systems: list[str] | None = None) -> int:
    from datetime import datetime, timezone

    systems = systems or index.ad_systems()
    fetcher = Fetcher(user_agent="adtx-attribution/0.1 (+https://github.com/OWNER/adtx-attribution)",
                      max_requests=len(systems) + 100)
    now = datetime.now(timezone.utc).isoformat()
    rows: list[tuple] = []

    for adsystem in systems:
        data = await fetcher.get_json(f"https://{adsystem}/sellers.json")
        if not data:
            continue
        for s in data.get("sellers", []):
            sid = str(s.get("seller_id", "")).strip()
            if not sid:
                continue
            conf = int(s.get("is_confidential", 0) or 0)
            rows.append((
                adsystem, sid,
                None if conf else s.get("name"),
                None if conf else (s.get("domain") or "").lower() or None,
                str(s.get("seller_type", "")).upper() or None,
                conf, now,
            ))
    await fetcher.aclose()
    index.conn.executemany("INSERT OR REPLACE INTO seller VALUES (?,?,?,?,?,?,?)", rows)
    index.conn.commit()
    return len(rows)


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="adtx-index")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="crawl ads.txt for a domain list")
    b.add_argument("--domains", required=True, help="newline-delimited domain file")
    b.add_argument("--db", default="adtx.sqlite")
    b.add_argument("--concurrency", type=int, default=20)

    s = sub.add_parser("sellers", help="crawl sellers.json for indexed ad systems")
    s.add_argument("--db", default="adtx.sqlite")

    q = sub.add_parser("lookup", help="reverse lookup")
    q.add_argument("--db", default="adtx.sqlite")
    q.add_argument("--seller", help="adsystem/seller_id")
    q.add_argument("--owner", help="owner domain")
    q.add_argument("--name", help="legal entity name")

    st = sub.add_parser("stats")
    st.add_argument("--db", default="adtx.sqlite")

    a = ap.parse_args(argv)
    idx = AdsTxtIndex(a.db)

    if a.cmd == "build":
        domains = [d.strip().lower() for d in Path(a.domains).read_text().splitlines() if d.strip()]
        n = asyncio.run(crawl_ads_txt(idx, domains, a.concurrency))
        print(f"{n} ads.txt records from {len(domains)} domains")
    elif a.cmd == "sellers":
        n = asyncio.run(crawl_sellers_json(idx))
        print(f"{n} seller records")
    elif a.cmd == "lookup":
        if a.seller:
            adsystem, sid = a.seller.split("/", 1)
            for d in idx.sites_for_seller(adsystem, sid):
                print(d)
        if a.owner:
            for d in idx.sites_for_owner(a.owner):
                print(d)
        if a.name:
            for row in idx.sellers_for_name(a.name):
                print("/".join(filter(None, row)))
    elif a.cmd == "stats":
        print(json.dumps(idx.stats(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
