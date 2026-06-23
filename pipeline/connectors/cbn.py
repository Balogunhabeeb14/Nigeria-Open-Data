"""Connector for Central Bank of Nigeria (CBN) statistics."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from pipeline.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class CBNConnector(BaseConnector):
    """Connector for CBN Statistics (Excel bulk downloads, hash-based detection)."""

    source_id = "CBN"

    def discover(self) -> list[dict]:
        """Return indicator configs from the database configuration for CBN.

        We don't hit a catalog API here — CBN has no discovery endpoint.
        The full list of indicators is passed dynamically through the DB.
        This method simply returns a summary so the flow can iterate over them.
        """
        indicators = [
            {"id": ind["id"], "name": ind["name"]}
            for ind in self.config.get("indicators", [])
        ]
        logger.info("CBN: %d indicators declared in dynamic config", len(indicators))
        return indicators

    def fetch(self, dataset_config: dict, since: str | None = None) -> pd.DataFrame:
        """Download the CBN Excel file and return rows newer than `since`.

        Args:
            dataset_config: One indicator dict from SOURCE_REGISTRY (CBN section).
            since:          Last ingested period (e.g. '2023-12'). None = full load.

        Returns:
            Raw DataFrame with columns as they appear in the Excel sheet.
            Returns empty DataFrame if the file hash has not changed.
        """
        indicator_id = dataset_config["id"]
        excel_url = dataset_config["excel_url"]
        sheet_name = dataset_config.get("sheet", 0)

        # ── Step 1: download to landing zone ─────────────────────────────────
        filename = f"{indicator_id}.xlsx"
        local_path = self.landing_path(filename)
        new_hash = self._download_and_hash(excel_url, local_path)

        # ── Step 2: compare hash with manifest ───────────────────────────────
        # The warehouse module handles this; we just return the hash so the
        # flow can decide whether to skip.  We store it in dataset_config.
        dataset_config["_file_hash"] = new_hash
        dataset_config["_local_path"] = str(local_path)

        # ── Step 3: parse the workbook ────────────────────────────────────────
        logger.info("Parsing CBN Excel: %s (sheet=%s)", local_path.name, sheet_name)
        try:
            df = pd.read_excel(local_path, sheet_name=sheet_name, header=0)
        except Exception as exc:
            logger.error("Failed to parse %s sheet=%s: %s", filename, sheet_name, exc)
            return pd.DataFrame()

        # Drop completely empty rows (CBN workbooks often have trailing blanks)
        df.dropna(how="all", inplace=True)

        # ── Step 4: incremental filter ────────────────────────────────────────
        # CBN files typically have a 'Date' column (monthly YYYY-MM format).
        col_map = dataset_config.get("col_map", {})
        date_col = next((k for k, v in col_map.items() if v == "period"), None)

        if date_col and date_col in df.columns and since:
            try:
                df[date_col] = df[date_col].astype(str)
                df = df[df[date_col] > since]
                logger.info(
                    "CBN incremental filter: kept %d rows newer than %s", len(df), since
                )
            except Exception as exc:
                logger.warning("Could not apply incremental filter on %s: %s", date_col, exc)

        logger.info("CBN fetch returned %d rows for indicator=%s", len(df), indicator_id)
        return df

    # ── Private ───────────────────────────────────────────────────────────────

    def _download_and_hash(self, url: str, dest: Path) -> str:
        """Download file and return its SHA-256 hash (used for change detection)."""
        self._download_file(url, dest)
        file_hash = self.file_hash(dest)
        logger.debug("File hash for %s: %s", dest.name, file_hash)
        return file_hash
