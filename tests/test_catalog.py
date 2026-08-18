"""Registry catalog integrity."""

from adtx_attribution.catalog import coverage_report, load_catalog, query


def test_catalog_loads():
    assert len(load_catalog()) >= 25


def test_every_implemented_registry_names_a_real_collector():
    from adtx_attribution.collectors import registry
    known = set(registry())
    for r in load_catalog():
        if r.collector:
            assert r.collector in known, f"{r.name} -> unknown collector {r.collector}"


def test_implemented_registries_are_automatable():
    for r in load_catalog():
        if r.collector:
            assert r.automatable, f"{r.name} has a collector but is marked manual"


def test_manual_registries_are_catalogued_not_hidden():
    """Knowing a registry exists and must be searched by hand is the point."""
    manual = [r for r in load_catalog() if not r.automatable]
    assert manual
    assert all(r.notes or r.url for r in manual)


def test_key_requiring_registries_declare_env_var():
    for r in load_catalog():
        if r.access == "api_key" and r.automatable:
            assert r.auth_env or r.collector, r.name


def test_jurisdiction_query_includes_global_sources():
    rows = query(jurisdiction="IN")
    assert any(r.jurisdiction == "IN" for r in rows)
    assert any(r.jurisdiction == "XX" for r in rows)


def test_coverage_report_renders():
    out = coverage_report()
    assert "Registry coverage" in out and "Manual entries are catalogued" in out
