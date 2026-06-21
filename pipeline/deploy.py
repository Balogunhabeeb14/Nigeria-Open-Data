"""Orchestrates Prefect deployments for all registered sources and the file watcher.

Reads configurations dynamically from SOURCE_REGISTRY.
"""
from __future__ import annotations

import logging
import sys

from pipeline.config import list_source_ids, get_source_config
from pipeline.flows.file_watcher_flow import file_watcher_flow
from pipeline.flows.ingest_flow import ingest_flow
from pipeline.registry import source_registry
from pipeline.settings import settings

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


def build_deployments() -> list:
    """Build one Prefect deployment per registered source, plus the file watcher."""
    deployments = []

    try:
        source_ids = list_source_ids()
    except Exception as e:
        logger.warning(f"Could not list source IDs from database (maybe not initialized?): {e}")
        source_ids = []

    for source_id in source_ids:
        source = get_source_config(source_id)
        cron = source.get("schedule")
        
        # Only create scheduled deployments for those with a cron
        if not cron:
            continue

        deployment = ingest_flow.to_deployment(
            name=f"{source_id.lower()}-ingestion",
            cron=cron,
            parameters={"source_id": source_id},
            description=(
                f"Automated ingestion for {source_id}. "
                f"Domain: {source['domain']}. "
                f"Mode: {source.get('ingest_mode', 'api')}. "
                f"Schedule: {cron}."
            ),
            tags=["nigeria", source["domain"], source.get("ingest_mode", "api"), source_id.lower()],
        )
        deployments.append(deployment)
        logger.info("Registered deployment: %s-ingestion (cron=%s)", source_id, cron)

    # File watcher — always deployed, regardless of source registry
    watcher_deployment = file_watcher_flow.to_deployment(
        name="file-watcher",
        cron="*/15 * * * *",   # every 15 minutes
        description=(
            "Scans data/raw/ for new or changed files every 15 minutes. "
            "Triggers the appropriate source ingestion flow automatically."
        ),
        tags=["nigeria", "file-watcher", "event-driven"],
    )
    deployments.append(watcher_deployment)
    logger.info("Registered deployment: file-watcher (every 15 min)")

    return deployments


def validate_registry() -> bool:
    """Validate all registered connectors and transforms are importable.

    Returns True if all valid, False if any errors found.
    Called before deployment to catch config mistakes early.
    """
    errors = source_registry.validate_all()
    if errors:
        for source_id, msgs in errors.items():
            for msg in msgs:
                logger.error("Registry error [%s]: %s", source_id, msg)
        return False
    try:
        count = len(list_source_ids())
    except:
        count = 0
    logger.info("Registry validation passed for %d sources.", count)
    return True


def main() -> None:
    logger.info("=== Nigeria Open Data Pipeline — Deploying Flows ===")
    logger.info("Settings: %s", settings)

    # Validate all connectors/transforms are importable before deploying
    if not validate_registry():
        logger.error("Registry validation failed. Fix the errors above and retry.")
        sys.exit(1)

    deployments = build_deployments()
    logger.info("Starting Prefect serve with %d deployments...", len(deployments))

    # serve() blocks — runs all scheduled flows in-process
    from prefect import serve
    serve(*deployments)


if __name__ == "__main__":
    main()
