"""adtx-attribution: ad-tech supply-chain collectors for attribution-graph.

Turns the monetization layer into an attribution surface. An operator can hide
registrant, hosting and email; to be paid, a real legal entity must be named to
the ad system, and sellers.json publishes that name.
"""

from .catalog import Registry, coverage_report, load_catalog, query
from .collectors import build_all, registry
from .index import AdsTxtIndex, crawl_ads_txt, crawl_sellers_json
from .ingest import from_opencti_bundle, from_spiderfoot_csv, from_spiderfoot_db
from .net import Fetcher
from .robin_ingest import from_robin, to_handle_observations

__version__ = "0.5.0"
__all__ = [
    "AdsTxtIndex", "crawl_ads_txt", "crawl_sellers_json",
    "Registry", "load_catalog", "query", "coverage_report",
    "from_spiderfoot_csv", "from_spiderfoot_db", "from_opencti_bundle",
    "from_robin", "to_handle_observations",
    "Fetcher", "build_all", "registry", "__version__",
]
