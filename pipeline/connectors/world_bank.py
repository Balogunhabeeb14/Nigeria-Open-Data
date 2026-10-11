"""Connector for the World Bank Indicators API (World Development Indicators).

API reference: https://datahelpdesk.worldbank.org/knowledgebase/topics/125589

Two calls are used, both anonymous JSON:

    GET /v2/source/2/indicators?format=json&per_page=500&page=N
        The catalogue of WDI indicators: code, name, description, topics.

    GET /v2/country/NGA/indicator/<code>?format=json&per_page=1000
        One indicator's full annual series for Nigeria.

Response shape of both: a two-element array, [metadata, records]. Errors come
back with HTTP 200 and a one-element array, [{"message": [{"id", "key",
"value"}]}], so the body has to be checked and not only the status code.

The whole series is fetched on every run and `since` is ignored. A series is
at most ~70 rows, and the World Bank revises past years, so an incremental
fetch would silently keep stale values. Unchanged series are skipped later by
the flow's content hash, which costs nothing extra here.
"""
from __future__ import annotations

import logging
import os
import re
import time

import pandas as pd

from pipeline.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

# Overridable so tests and offline demos can point at a recorded copy.
_API_BASE = os.environ.get("WORLD_BANK_API_BASE", "https://api.worldbank.org/v2").rstrip("/")
_WDI_SOURCE_ID = 2
_PAGE_SIZE_CATALOGUE = 500
_PAGE_SIZE_DATA = 1000

# The first part of an indicator code says what it measures more reliably
# than the World Bank's broad topics do. Checked before the topic.
_CODE_DOMAINS: list[tuple[str, str]] = [
    ("DT.", "debt"), ("GC.DOD", "debt"),
    ("GC.", "government"), ("IQ.", "government"), ("CC.", "government"), ("GE.", "government"),
    ("PV.", "government"), ("RL.", "government"), ("RQ.", "government"), ("VA.", "government"),
    ("IS.", "transport"), ("LP.", "transport"),
    ("TM.", "trade"), ("TX.", "trade"), ("TG.", "trade"), ("TT.", "trade"),
    ("EG.", "energy"), ("AG.", "agriculture"),
]

# World Bank topic name (lower-cased keyword) → platform domain / CKAN group.
# Matched in order; the first topic of an indicator that matches wins.
_TOPIC_DOMAINS: list[tuple[str, str]] = [
    ("agriculture", "agriculture"),
    ("education", "education"),
    ("health", "health"),
    ("energy", "energy"),
    ("climate", "environment"),
    ("environment", "environment"),
    ("infrastructure", "infrastructure"),
    ("science", "science-technology"),
    ("gender", "gender"),
    ("poverty", "poverty"),
    ("social protection", "labour"),
    ("social development", "society"),
    ("urban", "urban"),
    ("public sector", "government"),
    ("private sector", "business"),
    ("trade", "economy"),
    ("debt", "economy"),
    ("financial", "economy"),
    ("aid", "economy"),
    ("economy", "economy"),
]


class WorldBankAPIError(RuntimeError):
    """The API answered with an error payload (bad code, bad parameter...)."""


class WorldBankConnector(BaseConnector):
    """World Development Indicators for one country (Nigeria by default)."""

    source_id = "WorldBank"

    # ── Catalogue ─────────────────────────────────────────────────────────────

    def databases(self) -> list[dict]:
        """The World Bank databases to read, in priority order.

        Configured in the source's options as [{"id": 2, "name": ..., "domain":
        ...}]. An indicator that appears in several databases is taken from
        the first one that lists it.
        """
        return self.options.get("databases") or [
            {"id": _WDI_SOURCE_ID, "name": "World Development Indicators"}
        ]

    def discover_database(self, database: dict) -> list[dict]:
        """Every indicator of one World Bank database, as indicator configs."""
        found: list[dict] = []
        default_domain = database.get("domain") or self.config.get("domain", "economy")
        page, pages = 1, 1
        while page <= pages:
            url = (
                f"{_API_BASE}/source/{database['id']}/indicators"
                f"?format=json&per_page={_PAGE_SIZE_CATALOGUE}&page={page}"
            )
            meta, records = self._get_json(url)
            pages = _to_int(meta.get("pages"), default=1)
            for rec in records or []:
                code = (rec.get("id") or "").strip()
                name = (rec.get("name") or "").strip()
                if not code or not name:
                    continue
                found.append({
                    "id": indicator_id_for(code),
                    "name": name,
                    "dataset_id": code,
                    "wb_source": int(database["id"]),
                    "database": database.get("name") or f"World Bank database {database['id']}",
                    "domain": domain_for(code, rec.get("topics") or [], default_domain),
                    "unit": unit_from_name(name),
                    "description": (rec.get("sourceNote") or "").strip(),
                    "source_organization": (rec.get("sourceOrganization") or "").strip(),
                })
            page += 1
            self._pause()
        return found

    def discover(self) -> list[dict]:
        """Every indicator across the configured databases, without repeats.

        A database that cannot be listed is skipped with a warning so the
        others still load. Each dict carries id, name, dataset_id (the World
        Bank code), domain, unit and description, ready for the ingest flow.
        """
        found: list[dict] = []
        seen: set[str] = set()
        failures = 0
        for database in self.databases():
            try:
                listed = self.discover_database(database)
            except Exception as exc:
                failures += 1
                logger.warning("WorldBank: could not list database %s (%s)", database.get("id"), exc)
                continue
            fresh = [i for i in listed if i["dataset_id"] not in seen]
            seen.update(i["dataset_id"] for i in fresh)
            found.extend(fresh)
            logger.info(
                "WorldBank: %s lists %d indicators (%d new)",
                database.get("name") or database.get("id"), len(listed), len(fresh),
            )
        if not found and failures:
            raise WorldBankAPIError("No World Bank database could be listed")
        logger.info("WorldBank: catalogue lists %d indicators", len(found))
        return found

    def expand_indicators(self) -> list[dict]:
        """Featured indicators first, then everything else the catalogue lists.

        Catalogue details (official name, description) are merged into the
        featured entries, whose domain is kept. If the catalogue cannot be
        read, the featured list alone is returned so the run still does the
        most important work.
        """
        featured = list(self.config.get("indicators", []))
        if not self.options.get("discover"):
            return featured

        try:
            catalogue = self.discover()
        except Exception as exc:  # network, API error, unexpected shape
            logger.warning(
                "WorldBank: catalogue discovery failed (%s). "
                "Continuing with the %d featured indicators.", exc, len(featured),
            )
            return featured

        by_code = {c["dataset_id"]: c for c in catalogue}
        merged: list[dict] = []
        seen: set[str] = set()
        for cfg in featured:
            code = cfg["dataset_id"]
            extra = by_code.get(code, {})
            merged.append({**extra, **cfg, "name": extra.get("name") or cfg["name"], "featured": True})
            seen.add(code)

        rest = [c for c in catalogue if c["dataset_id"] not in seen]
        cap = self.options.get("max_indicators")
        if cap is not None:
            rest = rest[: max(0, int(cap) - len(merged))]
        merged.extend(rest)
        logger.info(
            "WorldBank: %d indicators to process (%d featured, %d discovered)",
            len(merged), len(featured), len(merged) - len(featured),
        )
        return merged

    # ── Data ──────────────────────────────────────────────────────────────────

    def fetch(self, dataset_config: dict, since: str | None = None) -> pd.DataFrame:
        """Return one indicator's full series as REF_AREA, TIME_PERIOD, OBS_VALUE.

        Years with no value are dropped. An indicator with no Nigeria data
        gives an empty frame, which the flow records as skipped.
        """
        code = dataset_config["dataset_id"]
        country = self.options.get("country", "NGA")
        wb_source = int(dataset_config.get("wb_source") or _WDI_SOURCE_ID)

        rows: list[dict] = []
        page, pages = 1, 1
        while page <= pages:
            url = (
                f"{_API_BASE}/country/{country}/indicator/{code}"
                f"?format=json&per_page={_PAGE_SIZE_DATA}&page={page}&source={wb_source}"
            )
            meta, records = self._get_json(url)
            pages = _to_int(meta.get("pages"), default=1)
            for rec in records or []:
                value = rec.get("value")
                period = normalise_period(str(rec.get("date") or ""))
                if value is None or not period:
                    continue
                rows.append({
                    "REF_AREA": ((rec.get("country") or {}).get("id") or "NG").upper(),
                    "TIME_PERIOD": period,
                    "OBS_VALUE": value,
                    "INDICATOR": code,
                })
            page += 1

        self._pause()
        df = pd.DataFrame(rows, columns=["REF_AREA", "TIME_PERIOD", "OBS_VALUE", "INDICATOR"])
        if not df.empty:
            df = df.sort_values("TIME_PERIOD").reset_index(drop=True)
        logger.info("WorldBank: %s returned %d observations", code, len(df))
        return df

    # ── Private ───────────────────────────────────────────────────────────────

    def _get_json(self, url: str) -> tuple[dict, list | None]:
        """GET a World Bank endpoint and return (metadata, records).

        Raises WorldBankAPIError when the body is an error payload or is not
        the two-element array the API documents.
        """
        payload = self._http_get(url).json()

        if isinstance(payload, list) and payload and isinstance(payload[0], dict) and "message" in payload[0]:
            messages = payload[0]["message"]
            detail = "; ".join(
                f"{m.get('key', 'error')}: {m.get('value', '')}" for m in messages if isinstance(m, dict)
            )
            raise WorldBankAPIError(f"World Bank API error for {url}: {detail}")

        if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[0], dict):
            raise WorldBankAPIError(f"Unexpected World Bank response shape for {url}")

        return payload[0], payload[1]

    def _pause(self) -> None:
        delay = float(self.options.get("request_delay_seconds") or 0)
        if delay > 0:
            time.sleep(delay)


# ── Helpers (also used by the transform and tests) ────────────────────────────

def indicator_id_for(code: str) -> str:
    """'NY.GDP.MKTP.CD' → 'WB_NY_GDP_MKTP_CD' (the platform's indicator id)."""
    return "WB_" + re.sub(r"[^A-Za-z0-9]+", "_", code).strip("_").upper()


def unit_from_name(name: str) -> str | None:
    """Read the unit from the brackets in an indicator name.

    'GDP growth (annual %)'                              → 'annual %'
    'Unemployment, total (% of total labor force)
        (modeled ILO estimate)'                          → '% of total labor force'
    'Maternal mortality ratio (modeled estimate,
        per 100,000 live births)'                        → 'per 100,000 live births'
    'Population, total'                                  → None

    Brackets that only say how the figure was produced ("modeled ILO
    estimate") are not units and are passed over.
    """
    groups = [g.strip() for g in re.findall(r"\(([^()]*)\)", name or "")]
    if not groups:
        return None
    units = [g for g in groups if not re.search(r"estimate", g, re.IGNORECASE)]
    if units:
        return units[-1] or None
    remainder = re.sub(r"^.*?estimate,?\s*", "", groups[-1], flags=re.IGNORECASE).strip()
    return remainder or None


def normalise_period(date: str) -> str:
    """World Bank dates → platform periods.

    '2024' and '2024Q1' pass through; monthly '2024M03' becomes '2024-03'.
    """
    date = date.strip()
    monthly = re.fullmatch(r"(\d{4})M(\d{2})", date)
    return f"{monthly.group(1)}-{monthly.group(2)}" if monthly else date


def domain_for(code: str, topics: list[dict], default: str) -> str:
    """Topic for an indicator: by its code first, then the World Bank's topic."""
    for prefix, domain in _CODE_DOMAINS:
        if code.startswith(prefix):
            return domain
    return _domain_for(topics, default)


def _domain_for(topics: list[dict], default: str) -> str:
    for topic in topics:
        label = str((topic or {}).get("value") or "").lower()
        for keyword, domain in _TOPIC_DOMAINS:
            if keyword in label:
                return domain
    return default


def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
