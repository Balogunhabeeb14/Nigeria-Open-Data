"""
pipeline/transforms/nigeria_data_portal_transform.py
======================================================
Maps raw data from the Nigeria Data Portal (SDMX-JSON or CSV)
into CDMRecord objects.

The raw DataFrame may come from either the JSON API or the CSV bulk export.
Both sources share the same SDMX dimension naming convention:
  REF_AREA       → geo_code   (ISO country/region code, e.g. 'NG')
  TIME_PERIOD    → period     (e.g. '2023', '2023Q1')
  OBS_VALUE      → value      (numeric)
  INDICATOR      → used to look up indicator_id from dataset_config

If the CSV path is used (no SDMX structure), column names vary.
We handle both cases with a priority-based column lookup.
"""
from __future__ import annotations

import logging

import pandas as pd

from pipeline.transforms.cdm import CDMRecord, infer_period_type

logger = logging.getLogger(__name__)

# Map of SDMX REF_AREA codes → human-readable geo_name
# Extend this as needed (state-level codes differ by source)
_GEO_NAME_MAP: dict[str, str] = {
    "NG":     "Nigeria",
    "NG-AB":  "Abia",
    "NG-AD":  "Adamawa",
    "NG-AK":  "Akwa Ibom",
    "NG-AN":  "Anambra",
    "NG-BA":  "Bauchi",
    "NG-BY":  "Bayelsa",
    "NG-BE":  "Benue",
    "NG-BO":  "Borno",
    "NG-CR":  "Cross River",
    "NG-DE":  "Delta",
    "NG-EB":  "Ebonyi",
    "NG-ED":  "Edo",
    "NG-EK":  "Ekiti",
    "NG-EN":  "Enugu",
    "NG-FC":  "FCT Abuja",
    "NG-GO":  "Gombe",
    "NG-IM":  "Imo",
    "NG-JI":  "Jigawa",
    "NG-KD":  "Kaduna",
    "NG-KN":  "Kano",
    "NG-KT":  "Katsina",
    "NG-KE":  "Kebbi",
    "NG-KO":  "Kogi",
    "NG-KW":  "Kwara",
    "NG-LA":  "Lagos",
    "NG-NA":  "Nasarawa",
    "NG-NI":  "Niger",
    "NG-OG":  "Ogun",
    "NG-ON":  "Ondo",
    "NG-OS":  "Osun",
    "NG-OY":  "Oyo",
    "NG-PL":  "Plateau",
    "NG-RI":  "Rivers",
    "NG-SO":  "Sokoto",
    "NG-TA":  "Taraba",
    "NG-YO":  "Yobe",
    "NG-ZA":  "Zamfara",
}


def transform(df: pd.DataFrame, dataset_config: dict) -> list[CDMRecord]:
    """Map a raw Nigeria Data Portal DataFrame to CDMRecord list.

    Args:
        df:             Raw DataFrame from NigeriaDataPortalConnector.fetch().
        dataset_config: The indicator config dict from SOURCE_REGISTRY.

    Returns:
        List of CDMRecord objects ready for upsert to cdm.indicator_observation.
    """
    if df.empty:
        return []

    indicator_id   = dataset_config["id"]
    indicator_name = dataset_config["name"]
    domain         = dataset_config.get("domain", "economics")
    unit           = dataset_config.get("unit", None)
    source_url     = f"https://nigeria.opendataforafrica.org/api/1.0/data/{dataset_config['dataset_id']}"

    records: list[CDMRecord] = []
    failed = 0

    for _, row in df.iterrows():
        try:
            geo_code = _get_column(row, ["REF_AREA", "Country", "region_code"], default="NG")
            period   = str(_get_column(row, ["TIME_PERIOD", "Year", "year", "Period"], default=""))
            raw_val  = _get_column(row, ["OBS_VALUE", "Value", "value"], default=None)

            if not period:
                logger.debug("Skipping row with empty period")
                failed += 1
                continue

            value: float | None = None
            if raw_val is not None and str(raw_val).strip() not in ("", "N/A", "nan"):
                try:
                    value = float(str(raw_val).replace(",", ""))
                except ValueError:
                    logger.debug("Cannot parse value '%s' for %s", raw_val, indicator_id)
                    failed += 1
                    continue

            # Determine geo level based on whether this is a national or state code
            geo_level = "state" if len(str(geo_code)) > 2 else "national"
            geo_name  = _GEO_NAME_MAP.get(str(geo_code).upper(), str(geo_code))

            records.append(CDMRecord(
                source_system  = "NigeriaDataPortal",
                domain         = domain,
                indicator_id   = indicator_id,
                indicator_name = indicator_name,
                geo_level      = geo_level,
                geo_code       = str(geo_code).upper(),
                geo_name       = geo_name,
                period_type    = infer_period_type(period),
                period         = period,
                value          = value,
                unit           = unit,
                raw_source_url = source_url,
            ))

        except Exception as exc:
            logger.warning("Row transform failed: %s | row=%s", exc, row.to_dict())
            failed += 1

    logger.info(
        "NigeriaDataPortal transform: %d records produced, %d rows failed for %s",
        len(records), failed, indicator_id,
    )
    return records


# ── Helper ────────────────────────────────────────────────────────────────────

def _get_column(row: pd.Series, candidates: list[str], default=None):
    """Return the first column value found from a priority list of column names."""
    for col in candidates:
        if col in row.index and pd.notna(row[col]):
            return row[col]
    return default
