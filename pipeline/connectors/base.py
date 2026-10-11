"""Base connector definitions for ingestion sources."""
from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd
import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from pipeline.settings import settings

logger = logging.getLogger(__name__)

# Sent with every request so source operators can see who is calling and why.
USER_AGENT = "NaijaOpenData-pipeline/1.0 (+https://github.com/Balogunhabeeb14/Nigeria-Open-Data)"


class BaseConnector(ABC):
    """Abstract connector. Subclass this for each data source.

    Subclasses must define class attributes:
        source_id   (str) — matches SOURCE_REGISTRY source_id
        landing_dir (str) — subfolder under settings.landing_root
    """

    source_id:   str  # must be set on subclass

    def __init__(self, config: dict | None = None) -> None:
        """Initialize with dynamic configuration from the database."""
        self.config = config or {}
        # Dynamically determine the landing folder (defaults to lowercase source_id)
        self.landing_dir = self.config.get(
            "landing_dir", 
            getattr(self, "landing_dir", self.source_id.lower())
        )

    # ── Public interface ──────────────────────────────────────────────────────

    @abstractmethod
    def discover(self) -> list[dict]:
        """Return available datasets/files from this source.

        Each dict must include at minimum: {"id": str, "name": str}
        """

    @abstractmethod
    def fetch(self, dataset_config: dict, since: str | None = None) -> pd.DataFrame:
        """Download and return raw data for one indicator/dataset.

        Args:
            dataset_config: The indicator config dict from SOURCE_REGISTRY.
            since:          Last ingested period (e.g. '2023Q4', '2024-01').
                            None → full historical load.

        Returns:
            Raw DataFrame (column names are source-specific; the transform handles mapping).
        """

    def expand_indicators(self) -> list[dict]:
        """Return the indicator configs this run should process.

        The default is the list stored with the source. Connectors that can
        ask the source what it offers (see WorldBankConnector) override this
        to add everything they discover, so coverage grows without anyone
        editing a list by hand.
        """
        return list(self.config.get("indicators", []))

    @property
    def options(self) -> dict:
        """Per-source settings from cdm.data_sources.options."""
        return self.config.get("options") or {}

    # ── Shared utilities ──────────────────────────────────────────────────────

    def landing_path(self, filename: str) -> Path:
        """Return the full local path for a file in this source's landing folder."""
        folder = settings.landing_root / self.landing_dir
        folder.mkdir(parents=True, exist_ok=True)
        return folder / filename

    @staticmethod
    def file_hash(path: Path) -> str:
        """Compute SHA-256 hash of a file. Used to detect unchanged files."""
        sha = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                sha.update(chunk)
        return sha.hexdigest()

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(settings.request_max_retries),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _http_get(self, url: str, **kwargs) -> requests.Response:
        """HTTP GET with automatic exponential-backoff retries.

        Retry count and timeout come from settings (not hardcoded).
        """
        logger.debug("GET %s", url)
        headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
        response = requests.get(
            url,
            timeout=settings.request_timeout_seconds,
            headers=headers,
            **kwargs,
        )
        response.raise_for_status()
        return response

    def _download_file(self, url: str, dest: Path) -> Path:
        """Stream a binary file to the landing zone.

        Uses streaming so large Excel/CSV files do not exhaust memory.
        Returns the local destination path.
        """
        logger.info("Downloading → %s", dest.name)
        with self._http_get(url, stream=True) as resp:
            with open(dest, "wb") as fout:
                for chunk in resp.iter_content(chunk_size=16_384):
                    fout.write(chunk)
        size_kb = dest.stat().st_size / 1024
        logger.info("Downloaded: %s (%.1f KB)", dest.name, size_kb)
        return dest
