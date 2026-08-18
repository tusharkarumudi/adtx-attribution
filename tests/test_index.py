"""Tests for the reverse ads.txt index and its role as a selectivity corpus."""

from datetime import datetime, timezone

import pytest
from attribution_graph import Identifier, IdKind

from adtx_attribution.index import AdsTxtIndex

NOW = datetime.now(timezone.utc).isoformat()


@pytest.fixture
def idx(tmp_path):
    ix = AdsTxtIndex(str(tmp_path / "t.sqlite"))
    rows = [
        ("a.example", "pubmatic.com", "156423", "DIRECT", NOW),
        ("b.example", "pubmatic.com", "156423", "DIRECT", NOW),
        ("c.example", "pubmatic.com", "156423", "RESELLER", NOW),
        ("d.example", "google.com", "pub-999", "DIRECT", NOW),
    ]
    ix.conn.executemany("INSERT OR REPLACE INTO ads_record VALUES (?,?,?,?,?)", rows)
    ix.conn.executemany("INSERT OR REPLACE INTO ads_var VALUES (?,?,?,?)", [
        ("a.example", "OWNERDOMAIN", "holdco.example", NOW),
        ("b.example", "OWNERDOMAIN", "holdco.example", NOW),
    ])
    ix.conn.executemany("INSERT OR REPLACE INTO seller VALUES (?,?,?,?,?,?,?)", [
        ("pubmatic.com", "156423", "Example Media Holdings Ltd",
         "holdco.example", "PUBLISHER", 0, NOW),
        ("google.com", "pub-999", None, None, "PUBLISHER", 1, NOW),
    ])
    ix.conn.commit()
    return ix


def test_reverse_seller_lookup_finds_portfolio(idx):
    """The pivot no free API exposes: seller ID -> every site declaring it."""
    assert idx.sites_for_seller("pubmatic.com", "156423") == [
        "a.example", "b.example", "c.example"
    ]


def test_ownerdomain_gives_self_published_portfolio(idx):
    assert idx.sites_for_owner("holdco.example") == ["a.example", "b.example"]


def test_holders_reflects_real_spread_not_case_view(idx):
    """A seller ID on three sites must not score as unique."""
    shared = Identifier(IdKind.SELLER_ID, "pubmatic.com/156423")
    lone = Identifier(IdKind.SELLER_ID, "google.com/pub-999")
    assert idx.holders(shared) == 3
    assert idx.holders(lone) == 1


def test_unknown_identifier_returns_zero_so_composite_falls_back(idx):
    assert idx.holders(Identifier(IdKind.SELLER_ID, "nope.com/1")) == 0
    assert idx.holders(Identifier(IdKind.EMAIL, "x@y.example")) == 0


def test_confidential_seller_keeps_type_but_not_name(idx):
    row = idx.conn.execute(
        "SELECT name, seller_type, is_confidential FROM seller WHERE seller_id='pub-999'"
    ).fetchone()
    assert row[0] is None and row[1] == "PUBLISHER" and row[2] == 1


def test_selectivity_index_protocol_satisfied(idx):
    from attribution_graph import SelectivityIndex
    assert isinstance(idx, SelectivityIndex)
