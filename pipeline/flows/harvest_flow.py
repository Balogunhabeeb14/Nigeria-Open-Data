"""Weekly catalogue harvest from other open data portals.

Run by hand:

    python -m pipeline.flows.harvest_flow                 # all enabled portals
    python -m pipeline.flows.harvest_flow hdx --limit 20  # one portal, first 20
    python -m pipeline.flows.harvest_flow --dry-run       # read only, write nothing
"""
from __future__ import annotations

from prefect import flow, get_run_logger, task

from pipeline.harvest.ckan_harvester import harvest_portal
from pipeline.harvest.portals import HARVEST_PORTALS, get_portal


@task(name="harvest_portal", retries=1, retry_delay_seconds=30)
def task_harvest(portal: dict, limit: int | None, dry_run: bool) -> dict:
    return harvest_portal(portal, limit=limit, dry_run=dry_run).as_dict()


@flow(name="harvest", description="List other portals' Nigeria datasets in the catalogue.")
def harvest_flow(
    portal_id: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict:
    """Harvest one portal, or every enabled portal when portal_id is None.

    A portal that is down or refuses the request is reported and the others
    still run.
    """
    log = get_run_logger()
    if not dry_run:
        from pipeline.db.warehouse import run_schema_migrations
        run_schema_migrations()

    portals = [get_portal(portal_id)] if portal_id else [p for p in HARVEST_PORTALS if p.get("enabled")]
    results: dict[str, dict] = {}
    for portal in portals:
        try:
            results[portal["id"]] = task_harvest(portal, limit, dry_run)
        except Exception as exc:
            log.error("Harvest of %s failed: %s", portal["id"], exc)
            results[portal["id"]] = {"portal": portal["id"], "failed": 1, "errors": [str(exc)]}
    log.info("Harvest complete: %s", results)
    return results


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Harvest dataset listings from other portals")
    parser.add_argument("portal", nargs="?", default=None, help="Portal id (default: all enabled)")
    parser.add_argument("--limit", type=int, default=None, help="Stop after N datasets per portal")
    parser.add_argument("--dry-run", action="store_true", help="Read and map only; write nothing")
    args = parser.parse_args()
    for portal, report in harvest_flow(args.portal, limit=args.limit, dry_run=args.dry_run).items():
        print(portal, report)


if __name__ == "__main__":
    main()
