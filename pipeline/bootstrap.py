"""Fill and refresh the catalogue without a Prefect server.

The steps are the same ones the Prefect deployments run, called directly
(see run_ingest in pipeline/flows/ingest_flow.py).

Used when the app runs on its own (CATALOG_BACKEND=local): one process that
loads data at start-up and again every REFRESH_HOURS.

Order matters for a first start, when the catalogue is empty:

    1. featured indicators of each source   (minutes; the site has content)
    2. listings from other portals          (minutes)
    3. everything else the sources offer    (can take a long while)

Settings (environment):
    BOOTSTRAP_SOURCES   comma-separated source ids      default: WorldBank
    BOOTSTRAP_HARVEST   true|false                      default: true
    BOOTSTRAP_FULL      true|false, run step 3          default: true
    REFRESH_HOURS       hours between refreshes; 0 = run once and exit
                                                        default: 168
"""
from __future__ import annotations

import logging
import os
import time

# Prefect's docstring parser warns about every flow parameter on import.
logging.getLogger("griffe").setLevel(logging.ERROR)

logger = logging.getLogger("bootstrap")


def _configure_logging() -> None:
    """Send the loader's progress to stderr.

    Done explicitly, after the pipeline is imported: importing Prefect resets
    the root logger to WARNING, which would hide every progress line.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
    for name, level in (
        ("bootstrap", logging.INFO),
        ("pipeline", logging.WARNING),
        ("pipeline.flows.ingest_flow", logging.INFO),   # one line per indicator
        ("pipeline.harvest", logging.INFO),
    ):
        log = logging.getLogger(name)
        log.setLevel(level)
        if name in ("bootstrap", "pipeline"):
            log.handlers = [handler]
            log.propagate = False


def _flag(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _counts(summary: dict) -> dict:
    counts: dict[str, int] = {}
    for item in summary.values():
        counts[item.get("status", "?")] = counts.get(item.get("status", "?"), 0) + 1
    return counts


def run_once() -> None:
    # Direct runs: no Prefect server is involved in standalone mode.
    from pipeline.db.warehouse import run_schema_migrations
    from pipeline.flows.ingest_flow import run_ingest as ingest_flow
    from pipeline.harvest.ckan_harvester import harvest_portal
    from pipeline.harvest.portals import HARVEST_PORTALS

    _configure_logging()
    run_schema_migrations()

    sources = [s.strip() for s in os.environ.get("BOOTSTRAP_SOURCES", "WorldBank").split(",") if s.strip()]

    for source in sources:
        try:
            logger.info("Step 1: featured indicators of %s", source)
            logger.info("%s featured: %s", source, _counts(ingest_flow(source, featured_only=True)))
        except Exception:
            logger.exception("Featured load of %s failed", source)

    if _flag("BOOTSTRAP_HARVEST", True):
        logger.info("Step 2: listings from other portals")
        for portal in (p for p in HARVEST_PORTALS if p.get("enabled")):
            try:
                harvest_portal(portal)      # logs its own summary line
            except Exception as exc:
                # A portal that is down or refuses us must not stop the rest.
                logger.error("Harvest of %s failed: %s", portal["id"], exc)

    if _flag("BOOTSTRAP_FULL", True):
        for source in sources:
            try:
                logger.info("Step 3: everything %s offers", source)
                logger.info("%s full: %s", source, _counts(ingest_flow(source)))
            except Exception:
                logger.exception("Full load of %s failed", source)


def main() -> None:
    refresh_hours = float(os.environ.get("REFRESH_HOURS", "168"))
    while True:
        started = time.time()
        run_once()
        logger.info("Load finished in %.0f minutes.", (time.time() - started) / 60)
        if refresh_hours <= 0:
            return
        logger.info("Next refresh in %.0f hours.", refresh_hours)
        time.sleep(refresh_hours * 3600)


if __name__ == "__main__":
    main()
