from __future__ import annotations
import logging
import pandas as pd
from pathlib import Path
from typing import Optional

from pipeline.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

class GenericFileConnector(BaseConnector):
    """
    A generic connector that reads uploaded CSV, Excel, or PDF files 
    from the source's landing directory.
    """
    source_id = "generic_file"

    def discover(self) -> list[dict]:
        return []

    def fetch(self, dataset_config: dict, since: Optional[str] = None) -> pd.DataFrame:
        from pipeline.settings import settings
        
        landing_dir = settings.landing_root / self.landing_dir
        
        if not landing_dir.exists():
            logger.warning(f"Landing directory does not exist: {landing_dir}")
            return pd.DataFrame()
            
        dfs = []
        for file_path in landing_dir.iterdir():
            suffix = file_path.suffix.lower()
            if suffix == ".csv":
                logger.info(f"Reading CSV: {file_path}")
                df = pd.read_csv(file_path)
                dfs.append(df)
                dataset_config["_file_meta"] = self._build_meta(file_path, "csv")
            elif suffix in [".xlsx", ".xls"]:
                logger.info(f"Reading Excel: {file_path}")
                df = pd.read_excel(file_path)
                dfs.append(df)
                dataset_config["_file_meta"] = self._build_meta(file_path, "excel")
            elif suffix == ".pdf":
                logger.info(f"Reading PDF: {file_path}")
                try:
                    df = self._extract_pdf_tables(file_path)
                    dfs.append(df)
                    dataset_config["_file_meta"] = self._build_meta(file_path, "pdf", status="success")
                except Exception as e:
                    logger.error(f"Failed to extract PDF {file_path}: {e}")
                    dataset_config["_file_meta"] = self._build_meta(file_path, "pdf", status="failed_extraction", error=str(e))
        
        if dfs and not all(df.empty for df in dfs):
            # Concat non-empty dataframes
            non_empty = [df for df in dfs if not df.empty]
            if non_empty:
                return pd.concat(non_empty, ignore_index=True)
        return pd.DataFrame()

    def _extract_pdf_tables(self, file_path: Path) -> pd.DataFrame:
        """Extract tables from PDF using pdfplumber."""
        import pdfplumber
        
        all_tables = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                table = page.extract_table()
                if table:
                    all_tables.extend(table)
        
        if not all_tables:
            return pd.DataFrame()
            
        # The first row of the first table is usually the header
        header = all_tables[0]
        # Sometimes header rows contain None, replace them with empty strings
        header = [str(h) if h is not None else "" for h in header]
        
        data_rows = all_tables[1:]
        
        df = pd.DataFrame(data_rows, columns=header)
        # Clean up the dataframe by dropping empty rows and columns
        df.dropna(how="all", inplace=True)
        return df

    def _build_meta(self, file_path: Path, format: str, status: str = "success", error: str = "") -> dict:
        return {
            "file_name": file_path.name,
            "file_path": str(file_path.absolute()),
            "format": format,
            "size_bytes": file_path.stat().st_size,
            "hash": self.file_hash(file_path),
            "status": status,
            "error_message": error
        }
