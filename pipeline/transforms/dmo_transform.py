"""Maps DMO state debt rows to CDMRecord objects."""
from __future__ import annotations

import pandas as pd

from pipeline.geo import STATES
from pipeline.transforms.cdm import CDMRecord


def transform(df: pd.DataFrame, dataset_config: dict) -> list[CDMRecord]:
    if df.empty:
        return []

    records: list[CDMRecord] = []
    for row in df.itertuples(index=False):
        code = str(row.REF_AREA)
        national = code == "NG"
        note = row.NOTE if isinstance(row.NOTE, str) and row.NOTE else None
        records.append(CDMRecord(
            source_system="DMO",
            domain=dataset_config.get("domain", "debt"),
            indicator_id=dataset_config["id"],
            indicator_name=dataset_config["name"],
            geo_level="national" if national else "state",
            geo_code=code,
            geo_name="Nigeria" if national else STATES.get(code, code),
            period_type="quarter",
            period=str(row.TIME_PERIOD),
            value=float(row.OBS_VALUE),
            unit=dataset_config.get("unit", "naira"),
            notes=note,
            raw_source_url=str(row.SOURCE_URL),
        ))
    return records
