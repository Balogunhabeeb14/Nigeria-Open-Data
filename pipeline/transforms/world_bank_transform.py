"""Maps World Bank indicator rows to CDMRecord objects.

Input columns (from WorldBankConnector.fetch): REF_AREA, TIME_PERIOD,
OBS_VALUE, INDICATOR. World Development Indicators are annual and national,
so every record is geo_level='national' with a four-digit year as its period.
"""
from __future__ import annotations

import logging

import pandas as pd

from pipeline.connectors.world_bank import unit_from_name
from pipeline.transforms.cdm import CDMRecord, infer_period_type

logger = logging.getLogger(__name__)

_COUNTRY_NAMES = {"NG": "Nigeria"}


def transform(df: pd.DataFrame, dataset_config: dict) -> list[CDMRecord]:
    """Map a World Bank DataFrame to a list of CDMRecord."""
    if df.empty:
        return []

    code = dataset_config["dataset_id"]
    name = dataset_config["name"]
    unit = dataset_config.get("unit") or unit_from_name(name)
    domain = dataset_config.get("domain", "economy")
    source_url = f"https://data.worldbank.org/indicator/{code}?locations=NG"
    notes = dataset_config.get("source_organization") or None

    records: list[CDMRecord] = []
    skipped = 0
    for row in df.itertuples(index=False):
        try:
            value = float(row.OBS_VALUE)
        except (TypeError, ValueError):
            skipped += 1
            continue
        if pd.isna(value):
            skipped += 1
            continue

        period = str(row.TIME_PERIOD).strip()
        geo_code = str(row.REF_AREA).upper()
        records.append(CDMRecord(
            source_system="WorldBank",
            domain=domain,
            indicator_id=dataset_config["id"],
            indicator_name=name,
            geo_level="national",
            geo_code=geo_code,
            geo_name=_COUNTRY_NAMES.get(geo_code, geo_code),
            period_type=infer_period_type(period),
            period=period,
            value=value,
            unit=unit,
            notes=notes,
            raw_source_url=source_url,
        ))

    if skipped:
        logger.warning("WorldBank transform: skipped %d non-numeric rows for %s", skipped, code)
    return records
