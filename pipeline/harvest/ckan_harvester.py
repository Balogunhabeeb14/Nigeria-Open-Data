"""Harvest dataset listings from another CKAN portal into our catalogue.

    remote package_search  →  map to our fields  →  create / patch in our CKAN

Only catalogue entries are copied. Each harvested dataset links to the files
on the original portal and names that portal and the original publisher.

Change detection uses the remote `metadata_modified` timestamp, stored in
cdm.ingest_manifest under source_system 'harvest:<portal>'. A dataset whose
timestamp has not moved is not touched.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from pipeline.connectors.base import USER_AGENT
from pipeline.publisher import _clean_tag, _ensure_group, ensure_organization, slugify
from pipeline.settings import settings

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100
_PAGE_DELAY_SECONDS = 1.0
_MAX_TAGS = 15


@dataclass
class HarvestReport:
    portal: str
    seen: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    skip_reasons: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "portal": self.portal, "seen": self.seen, "created": self.created,
            "updated": self.updated, "unchanged": self.unchanged,
            "skipped": self.skipped, "skip_reasons": self.skip_reasons,
            "failed": self.failed, "errors": self.errors[:20],
        }


# ── Remote side ───────────────────────────────────────────────────────────────

@retry(
    retry=retry_if_exception_type(requests.RequestException),
    stop=stop_after_attempt(settings.request_max_retries),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
def _search_page(portal: dict, start: int, rows: int) -> dict:
    params = {"rows": rows, "start": start, "sort": "metadata_modified desc"}
    if portal.get("fq"):
        params["fq"] = portal["fq"]
    if portal.get("q"):
        params["q"] = portal["q"]
    resp = requests.get(
        f"{portal['base_url'].rstrip('/')}/api/3/action/package_search",
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=settings.request_timeout_seconds,
    )
    resp.raise_for_status()
    body = resp.json()
    if not body.get("success"):
        raise RuntimeError(f"{portal['id']}: package_search reported failure: {body.get('error')}")
    return body["result"]


def iter_remote_datasets(portal: dict, limit: int | None = None) -> Iterator[dict]:
    """Yield the portal's matching datasets, newest change first."""
    start, yielded = 0, 0
    while True:
        result = _search_page(portal, start, _PAGE_SIZE)
        batch = result.get("results") or []
        if not batch:
            return
        for dataset in batch:
            yield dataset
            yielded += 1
            if limit is not None and yielded >= limit:
                return
        start += len(batch)
        if start >= int(result.get("count") or 0):
            return
        time.sleep(_PAGE_DELAY_SECONDS)


# ── Mapping ───────────────────────────────────────────────────────────────────

def local_name_for(portal_id: str, remote_name: str) -> str:
    """'hdx' + 'nigeria-health-facilities' → 'hdx-nigeria-health-facilities'."""
    return slugify(f"{portal_id}-{remote_name}")


def _linkable(resource: dict) -> bool:
    url = resource.get("url") or resource.get("download_url")
    return bool(url) and str(url).lower().startswith(("http://", "https://"))


def skip_reason(remote: dict) -> str | None:
    """Why a remote dataset is not listed, or None if it should be.

    Reported per harvest so a portal that suddenly yields mostly skips is
    noticed and explained.
    """
    if remote.get("private"):
        return "private"
    if remote.get("archived"):
        return "archived by the portal"
    if remote.get("state") not in (None, "active"):
        return "not active"
    if not any(_linkable(r) for r in remote.get("resources") or []):
        return "no file to link to"
    return None


def map_dataset(portal: dict, remote: dict) -> dict | None:
    """Translate a remote CKAN dataset into the fields we store.

    Returns None for datasets we should not list: private or archived ones,
    and ones with no file to link to.
    """
    if skip_reason(remote):
        return None

    resources = []
    for res in remote.get("resources") or []:
        url = res.get("url") or res.get("download_url")
        if not url or not str(url).lower().startswith(("http://", "https://")):
            continue
        resources.append({
            "name": (res.get("name") or res.get("description") or "File")[:200],
            "url": url,
            "format": (res.get("format") or "").upper(),
            "description": (res.get("description") or "")[:1000],
        })
    if not resources:
        return None

    base = portal["base_url"].rstrip("/")
    remote_page = f"{base}/dataset/{remote['name']}"
    publisher = ((remote.get("organization") or {}).get("title")) or remote.get("dataset_source") or ""
    licence = remote.get("license_title") or remote.get("license_id") or "Not specified by the source"

    notes = (remote.get("notes") or "").strip()
    # Plain text, no markup (see publisher._build_package_fields).
    credit = (
        f"Listed from {portal['title']}."
        + (f" Original publisher: {publisher}." if publisher else "")
        + " The files are hosted by the original portal. Naija Open Data lists "
          "this dataset so it can be found in one place; it does not hold a copy."
    )

    tags = []
    for raw in ["nigeria", portal["id"], *[t.get("name", "") for t in remote.get("tags") or []]]:
        tag = _clean_tag(raw)
        if tag and tag.lower() not in {t["name"].lower() for t in tags}:
            tags.append({"name": tag})
        if len(tags) >= _MAX_TAGS:
            break

    extras = {
        "harvest_portal": portal["id"],
        "harvest_portal_title": portal["title"],
        "source": publisher or portal["title"],
        "source_url": remote_page,
        "licence_name": licence,
        "licence_url": remote.get("license_url") or "",
        "remote_id": remote.get("id") or "",
        "remote_metadata_modified": remote.get("metadata_modified") or "",
        "hosted": "external",
    }

    return {
        "name": local_name_for(portal["id"], remote["name"]),
        "title": (remote.get("title") or remote["name"])[:200],
        "notes": f"{notes}\n\n{credit}" if notes else credit,
        "url": remote_page,
        "license_id": remote.get("license_id") or "notspecified",
        "tags": tags,
        "extras": [{"key": k, "value": v} for k, v in extras.items() if v != ""],
        "resources": resources,
    }


# ── Local side ────────────────────────────────────────────────────────────────

def _ensure_org(ckan, portal: dict) -> str:
    """One organisation per portal, so users can filter by where a listing came from."""
    return ensure_organization(
        ckan, portal["id"], portal["title"],
        f"Datasets listed from {portal['title']} ({portal['base_url']}).",
    )


def harvest_portal(
    portal: dict,
    ckan=None,
    limit: int | None = None,
    dry_run: bool = False,
    track: bool = True,
) -> HarvestReport:
    """Harvest one portal. Never raises for a single bad dataset.

    Args:
        portal:  An entry from HARVEST_PORTALS.
        ckan:    CKAN client to write to (defaults to the configured one).
        limit:   Stop after this many remote datasets (None = all).
        dry_run: Read and map only; write nothing. Use it to check that a
                 portal answers and how many datasets it would list.
        track:   Use cdm.ingest_manifest to skip unchanged datasets.
    """
    from ckanapi import NotFound

    from pipeline.publisher import _get_ckan_client

    report = HarvestReport(portal=portal["id"])
    manifest_source = f"harvest:{portal['id']}"

    known: dict[str, str] = {}
    if track and not dry_run:
        from pipeline.db.warehouse import get_manifest_hashes, update_manifest
        known = get_manifest_hashes(manifest_source)

    if not dry_run:
        ckan = ckan or _get_ckan_client()
        if ckan is None:
            report.errors.append("CKAN_API_KEY not set; nothing was written.")
            return report
        owner_org = _ensure_org(ckan, portal)
        group = _ensure_group(ckan, portal.get("group"))

    for remote in iter_remote_datasets(portal, limit=limit):
        report.seen += 1
        remote_name = remote.get("name") or ""
        try:
            reason = skip_reason(remote)
            mapped = None if reason else map_dataset(portal, remote)
            if mapped is None:
                reason = reason or "could not be mapped"
                report.skipped += 1
                report.skip_reasons[reason] = report.skip_reasons.get(reason, 0) + 1
                continue

            stamp = remote.get("metadata_modified") or ""
            if stamp and known.get(remote_name) == stamp:
                report.unchanged += 1
                continue

            if dry_run:
                report.created += 1
                continue

            if group:
                mapped["groups"] = [{"name": group}]
            name = mapped.pop("name")
            try:
                existing = ckan.action.package_show(id=name)
            except NotFound:
                existing = None

            if existing is None:
                ckan.action.package_create(name=name, owner_org=owner_org, **mapped)
                report.created += 1
            else:
                ckan.action.package_patch(id=existing["id"], **mapped)
                report.updated += 1

            if track:
                update_manifest(
                    manifest_source, remote_name, None, len(mapped["resources"]),
                    content_hash=stamp or None, publish_state="published",
                )
        except Exception as exc:
            report.failed += 1
            report.errors.append(f"{remote_name}: {exc}")
            logger.warning("Harvest failed for %s/%s: %s", portal["id"], remote_name, exc)

    logger.info("Harvest %s: %s", portal["id"], report.as_dict())
    return report
