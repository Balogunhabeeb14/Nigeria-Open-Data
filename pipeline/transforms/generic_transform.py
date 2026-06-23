from typing import Iterator
from datetime import datetime, timezone
import pandas as pd

def generic_transform(raw_data: dict, source_cfg: dict) -> Iterator[dict]:
    """
    Dynamically maps rows from an uploaded dataset to the standard CDM schema.
    It expects the CSV to have columns matching the indicator IDs or names, 
    and ideally a 'date' or 'period' column.
    """
    
    # Try to find a date column
    date_cols = [k for k in raw_data.keys() if "date" in str(k).lower() or "period" in str(k).lower() or "year" in str(k).lower()]
    period_date = datetime.now(timezone.utc)
    if date_cols and pd.notna(raw_data.get(date_cols[0])):
        try:
            val = raw_data[date_cols[0]]
            if isinstance(val, str) and len(val) == 4 and val.isdigit():
                period_date = datetime(int(val), 1, 1, tzinfo=timezone.utc)
            else:
                period_date = pd.to_datetime(val).replace(tzinfo=timezone.utc)
        except:
            pass

    for ind in source_cfg.get("indicators", []):
        ind_id = ind["id"]
        ind_name = ind["name"]
        
        # Check if the raw data has this indicator's ID or name
        val = raw_data.get(ind_id) or raw_data.get(ind_name)
        
        if val is not None and pd.notna(val):
            yield {
                "indicator_id": ind_id,
                "period_date": period_date,
                "value_numeric": float(val) if str(val).replace('.', '', 1).isdigit() else None,
                "value_text": str(val) if not str(val).replace('.', '', 1).isdigit() else None,
                "unit": ind.get("unit", ""),
                "domain": ind.get("domain", source_cfg.get("domain", "general")),
                "source_id": source_cfg["source_id"]
            }
