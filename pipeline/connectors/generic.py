from typing import Iterator, Optional
import pandas as pd
from pathlib import Path

from pipeline.connectors.base import BaseConnector

class GenericFileConnector(BaseConnector):
    """
    A generic connector that reads uploaded CSV or Excel files 
    from the source's landing directory.
    """
    source_id: str = "generic_file"

    def discover(self) -> list[dict]:
        return []

    def fetch(self, dataset_config: dict, since: Optional[str] = None) -> pd.DataFrame:
        from pipeline.settings import settings
        import logging
        logger = logging.getLogger(__name__)

        landing_dir = settings.landing_root / self.landing_dir
        
        if not landing_dir.exists():
            logger.warning(f"Landing directory does not exist: {landing_dir}")
            return pd.DataFrame()
            
        dfs = []
        for file_path in landing_dir.iterdir():
            if file_path.suffix.lower() == ".csv":
                logger.info(f"Reading CSV: {file_path}")
                df = pd.read_csv(file_path)
                dfs.append(df)
            elif file_path.suffix.lower() in [".xlsx", ".xls"]:
                logger.info(f"Reading Excel: {file_path}")
                df = pd.read_excel(file_path)
                dfs.append(df)
        
        if dfs:
            return pd.concat(dfs, ignore_index=True)
        return pd.DataFrame()
