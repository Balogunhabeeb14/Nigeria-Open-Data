from __future__ import annotations
import logging
import pandas as pd
from datetime import datetime
from pipeline.transforms.cdm import CDMRecord, infer_period_type
from pipeline.config import get_source_config

logger = logging.getLogger(__name__)

def generic_transform(df: pd.DataFrame, dataset_config: dict) -> list[CDMRecord]:
    """
    Dynamically maps a DataFrame to the standard CDM schema.
    It expects the data to have columns matching the indicator IDs or names, 
    and ideally a 'date' or 'period' column.
    """
    if df.empty:
        return []

    source_id = dataset_config.get("source_id", "generic_file")
    
    # In some flow patterns we might receive the full source_config instead of an indicator config,
    # or the indicator config might be missing source_id.
    # We fetch the full config to find all indicators if we don't have them in the current dict.
    try:
        source_cfg = get_source_config(source_id)
    except KeyError:
        # Fallback if source is not in DB yet during tests
        source_cfg = {"domain": dataset_config.get("domain", "general")}

    indicators = dataset_config.get("indicators", [])
    if not indicators:
        # If we were passed an indicator config directly, we use it.
        # Otherwise, if we were passed a source config, we use its indicators.
        if "id" in dataset_config:
            indicators = [dataset_config]
        elif "indicators" in source_cfg:
            indicators = source_cfg["indicators"]

    # Try to find a date column
    date_cols = [k for k in df.columns if "date" in str(k).lower() or "period" in str(k).lower() or "year" in str(k).lower()]
    period_col = date_cols[0] if date_cols else None

    records: list[CDMRecord] = []
    failed = 0

    for ind in indicators:
        ind_id = ind["id"]
        ind_name = ind["name"]
        unit = ind.get("unit", "")
        domain = ind.get("domain", source_cfg.get("domain", "general"))
        
        # Check if the raw data has this indicator's ID or name as a column
        val_col = None
        for col in df.columns:
            if str(col).lower() in (ind_id.lower(), ind_name.lower()):
                val_col = col
                break
                
        if not val_col:
            continue

        for _, row in df.iterrows():
            try:
                val = row[val_col]
                if pd.isna(val):
                    continue

                period_str = str(datetime.now().year)
                if period_col and pd.notna(row[period_col]):
                    raw_period = row[period_col]
                    if isinstance(raw_period, str) and len(raw_period) == 4 and raw_period.isdigit():
                        period_str = raw_period
                    else:
                        try:
                            period_str = pd.to_datetime(raw_period).strftime("%Y-%m-%d")
                        except Exception:
                            period_str = str(raw_period)

                value_numeric = None
                raw_val_str = str(val).strip().replace(',', '')
                try:
                    value_numeric = float(raw_val_str)
                except ValueError:
                    # If it's not numeric, we might just store None for value but still create a record
                    # if the schema supports it. The CDM requires numeric value for now.
                    logger.debug(f"Non-numeric value skipped: {val}")
                    failed += 1
                    continue

                records.append(CDMRecord(
                    source_system=source_id,
                    domain=domain,
                    indicator_id=ind_id,
                    indicator_name=ind_name,
                    geo_level="national",
                    geo_code="NG",
                    geo_name="Nigeria",
                    period_type=infer_period_type(period_str),
                    period=period_str,
                    value=value_numeric,
                    unit=unit,
                    raw_source_url=None
                ))
            except Exception as e:
                logger.warning(f"Failed to transform row for {ind_id}: {e}")
                failed += 1

    logger.info(f"generic_transform: Produced {len(records)} records, {failed} failed")
    return records
