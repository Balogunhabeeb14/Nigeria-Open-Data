"""Connector for Nigeria Data Portal SDMX-JSON API and CSV fallback."""
from __future__ import annotations

import logging
from urllib.parse import urlencode

import pandas as pd

from pipeline.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

# Public SDMX-JSON API for the Africa Open Data platform
_API_BASE = "https://nigeria.opendataforafrica.org/api/1.0"
# Public CSV bulk-download endpoint fallback
_CSV_BASE = "https://nigeria.opendataforafrica.org/api/1.0/csv"


class NigeriaDataPortalConnector(BaseConnector):
    """Connector for nigeria.opendataforafrica.org (anonymous access)."""

    source_id = "NigeriaDataPortal"

    def discover(self) -> list[dict]:
        """Return the list of datasets available on the Nigeria Data Portal.

        We hit the AoD catalog endpoint and filter to Nigerian datasets.
        Returns a simplified list; the full indicator configuration comes dynamically
        from the database (self.config).
        """
        url = f"{_API_BASE}/datasets?country=NG"
        try:
            resp = self._http_get(url)
            catalog = resp.json()
            datasets = [
                {"id": d["id"], "name": d.get("name", d["id"])}
                for d in catalog.get("datasets", [])
            ]
            logger.info("NigeriaDataPortal: discovered %d datasets", len(datasets))
            return datasets
        except Exception as exc:
            logger.warning("NigeriaDataPortal discover failed: %s – returning empty list", exc)
            return []

    def fetch(self, dataset_config: dict, since: str | None = None) -> pd.DataFrame:
        """Fetch one indicator dataset, incrementally if `since` is provided.

        Tries the SDMX-JSON API first.  If that fails or returns no data,
        falls back to the CSV download endpoint.

        Args:
            dataset_config: Dict loaded from the database config for the indicator.
            since:          Last ingested period string (e.g. '2020', '2020Q1').
                            None = full history.

        Returns:
            Flat DataFrame with raw columns from the source.
        """
        dataset_id = dataset_config["dataset_id"]
        logger.info(
            "Fetching %s (indicator=%s, since=%s)",
            dataset_id, dataset_config["id"], since or "full history",
        )

        # Try JSON API first
        df = self._fetch_json_api(dataset_id, since)
        if df is not None and not df.empty:
            return df

        # Fallback: CSV bulk download
        logger.info("JSON API returned nothing for %s — falling back to CSV", dataset_id)
        df = self._fetch_csv_bulk(dataset_id, since)
        if df is not None and not df.empty:
            return df

        logger.warning("No data found for dataset_id=%s", dataset_id)
        return pd.DataFrame()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _fetch_json_api(self, dataset_id: str, since: str | None) -> pd.DataFrame | None:
        """Call the SDMX-JSON API and parse the response into a flat DataFrame."""
        params: dict[str, str] = {}
        if since:
            params["startPeriod"] = since

        url = f"{_API_BASE}/data/{dataset_id}"
        if params:
            url = f"{url}?{urlencode(params)}"

        try:
            resp = self._http_get(url)
            data = resp.json()
        except Exception as exc:
            logger.debug("JSON API error for %s: %s", dataset_id, exc)
            return None

        # ── Parse SDMX-JSON structure ─────────────────────────────────────
        # SDMX-JSON puts dimension names in structure.dimensions.observation
        # and values in dataSets[0].observations
        try:
            structure = data["structure"]
            dims = structure["dimensions"]["observation"]
            dim_names = [d["id"] for d in dims]
            dim_values = [d["values"] for d in dims]

            obs_dict = data["dataSets"][0]["observations"]
            records = []
            for key_str, obs_vals in obs_dict.items():
                indices = [int(i) for i in key_str.split(":")]
                row: dict = {}
                for dim_idx, dim_name in enumerate(dim_names):
                    row[dim_name] = dim_values[dim_idx][indices[dim_idx]]["id"]
                row["OBS_VALUE"] = obs_vals[0]  # first value = observation
                records.append(row)

            df = pd.DataFrame(records)
            logger.info("JSON API returned %d rows for %s", len(df), dataset_id)
            return df

        except (KeyError, IndexError) as exc:
            logger.debug("Could not parse SDMX-JSON for %s: %s", dataset_id, exc)
            return None

    def _fetch_csv_bulk(self, dataset_id: str, since: str | None) -> pd.DataFrame | None:
        """Download the CSV bulk export and optionally filter by `since`."""
        url = f"{_CSV_BASE}/{dataset_id}.csv"
        local_path = self.landing_path(f"{dataset_id}.csv")

        try:
            self._download_file(url, local_path)
            df = pd.read_csv(local_path)

            # Best-effort incremental filter on a 'Year' or 'TIME_PERIOD' column
            for col in ("TIME_PERIOD", "Year", "year"):
                if col in df.columns and since:
                    df = df[df[col].astype(str) >= since]
                    break

            logger.info("CSV bulk returned %d rows for %s", len(df), dataset_id)
            return df

        except Exception as exc:
            logger.warning("CSV bulk download failed for %s: %s", dataset_id, exc)
            return None
