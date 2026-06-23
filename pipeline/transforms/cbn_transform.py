"""
pipeline/transforms/cbn_transform.py
=====================================
Maps raw data from CBN Excel files into CDMRecord objects.

CBN Excel workbooks have inconsistent column names across tables.
Each indicator in SOURCE_REGISTRY["CBN"] carries a `col_map` dict that
tells us exactly which Excel column maps to which CDM field.

Example col_map:
    {"Date": "period", "MPR (%)": "value"}

This means we never need to hard-code CBN column names here —
adding a new indicator is purely a config change in config.py.
"""
from __future__ import annotations

import logging

import pandas as pd

from pipeline.transforms.cdm import CDMRecord, infer_period_type

logger = logging.getLogger(__name__)


def transform(df: pd.DataFrame, dataset_config: dict) -> list[CDMRecord]:
    """Map a raw CBN Excel DataFrame to CDMRecord list.

    Args:
        df:             Raw DataFrame from CBNConnector.fetch().
        dataset_config: The indicator config dict from SOURCE_REGISTRY (CBN).

    Returns:
        List of CDMRecord objects ready for upsert to cdm.indicator_observation.
    """
    if df.empty:
        return []

    indicator_id   = dataset_config["id"]
    indicator_name = dataset_config["name"]
    domain         = dataset_config.get("domain", "economics")
    unit           = dataset_config.get("unit", None)
    col_map        = dataset_config.get("col_map", {})
    source_url     = dataset_config.get("excel_url", "")

    # Resolve column names from col_map
    period_col = _find_col(col_map, "period", df.columns)
    value_col  = _find_col(col_map, "value",  df.columns)

    if not period_col or not value_col:
        logger.error(
            "CBN transform: cannot find period/value columns for %s. "
            "col_map=%s, available=%s",
            indicator_id, col_map, list(df.columns),
        )
        return []

    records: list[CDMRecord] = []
    failed = 0

    for _, row in df.iterrows():
        try:
            raw_period = row.get(period_col)
            raw_value  = row.get(value_col)

            if pd.isna(raw_period):
                failed += 1
                continue

            period = _normalise_period(raw_period)

            value: float | None = None
            if pd.notna(raw_value) and str(raw_value).strip() not in ("", "N/A"):
                try:
                    value = float(str(raw_value).replace(",", ""))
                except ValueError:
                    logger.debug(
                        "Cannot parse value '%s' for %s period=%s",
                        raw_value, indicator_id, period,
                    )
                    failed += 1
                    continue

            records.append(CDMRecord(
                source_system  = "CBN",
                domain         = domain,
                indicator_id   = indicator_id,
                indicator_name = indicator_name,
                geo_level      = "national",   # CBN data is always national-level
                geo_code       = "NG",
                geo_name       = "Nigeria",
                period_type    = infer_period_type(period),
                period         = period,
                value          = value,
                unit           = unit,
                raw_source_url = source_url,
            ))

        except Exception as exc:
            logger.warning("CBN row transform failed: %s | row=%s", exc, row.to_dict())
            failed += 1

    logger.info(
        "CBN transform: %d records produced, %d rows failed for %s",
        len(records), failed, indicator_id,
    )
    return records


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_col(col_map: dict, cdm_field: str, available_cols) -> str | None:
    """Given a col_map {raw_col: cdm_field}, find the raw_col for cdm_field."""
    for raw_col, mapped_field in col_map.items():
        if mapped_field == cdm_field and raw_col in available_cols:
            return raw_col
    return None


def _normalise_period(raw) -> str:
    """Normalise CBN date values to standard period strings.

    CBN files may have:
      - Timestamps: pd.Timestamp('2024-01-01') → '2024-01'
      - Strings: 'Jan-2024' → '2024-01', '2024Q1' → '2024Q1', '2024' → '2024'
    """
    if isinstance(raw, pd.Timestamp):
        return raw.strftime("%Y-%m")

    s = str(raw).strip()

    # Already in YYYY-MM or YYYY format
    if len(s) in (7, 4) and (s[4:5] in ("-", "") or s[4:5] == "Q"):
        return s

    # 'Jan-2024' style
    try:
        parsed = pd.to_datetime(s, dayfirst=False)
        return parsed.strftime("%Y-%m")
    except Exception:
        pass

    return s  # return as-is; CDM will store it
