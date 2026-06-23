"""Generic, parameterized data ingestion flow.

Handles discovery, fetching, validation, staging, transformation, database loading,
and CKAN catalog publishing for any registered source.
"""
from __future__ import annotations

import logging
from typing import cast

import pandas as pd
from prefect import flow, get_run_logger, task

from pipeline.config import get_source_config
from pipeline.publisher import publish_indicator_to_ckan
from pipeline.quality.checks import QualityRunner
from pipeline.registry import source_registry

logger = logging.getLogger(__name__)


@task(name="fetch_data", retries=3, retry_delay_seconds=60)
def task_fetch(
    source_id: str,
    indicator_config: dict,
    start_period: str | None,
) -> pd.DataFrame:
    from pipeline.db.warehouse import get_watermark

    log = get_run_logger()
    indicator_id = indicator_config["id"]
    since = start_period or get_watermark(source_id, indicator_id)
    log.info("[%s/%s] Fetching (since=%s)", source_id, indicator_id, since or "full history")

    connector = source_registry.get_connector(source_id)
    df = connector.fetch(indicator_config, since=since)
    log.info("[%s/%s] Fetched %d rows", source_id, indicator_id, len(df))
    return df


@task(name="validate_data")
def task_validate(
    source_id: str,
    indicator_config: dict,
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Run quality checks. Raises RuntimeError on CRITICAL failures (halts the task)."""
    log = get_run_logger()
    runner = QualityRunner(source=source_id, indicator_id=indicator_config["id"])
    report = runner.run(df, indicator_config)
    log.info(report.summary())

    if report.has_critical_failures:
        raise RuntimeError(
            f"CRITICAL quality failure for {source_id}/{indicator_config['id']}. "
            "Data rejected — not loaded. Review logs for details."
        )
    if report.has_warnings:
        log.warning(
            "[%s/%s] Quality warnings present — data loaded with caveats.",
            source_id, indicator_config["id"],
        )
    return df


@task(name="stage_raw_data")
def task_stage(
    source_id: str,
    indicator_config: dict,
    df: pd.DataFrame,
) -> int:
    """Insert raw rows into cdm.stage_raw_observations for full audit trail."""
    from pipeline.db.warehouse import load_to_stage

    log = get_run_logger()
    n = load_to_stage(
        df,
        source_id,
        indicator_config["id"],
        file_or_url=indicator_config.get("excel_url") or indicator_config.get("dataset_id"),
    )
    log.info("[%s/%s] Staged %d raw rows", source_id, indicator_config["id"], n)
    return n


@task(name="transform_to_cdm")
def task_transform(
    source_id: str,
    indicator_config: dict,
    df: pd.DataFrame,
) -> list:
    """Map raw DataFrame → CDMRecord list using the registered transform function."""
    log = get_run_logger()
    transform_fn = source_registry.get_transform(source_id)
    records = transform_fn(df, indicator_config)
    log.info("[%s/%s] Transformed %d CDM records", source_id, indicator_config["id"], len(records))
    return records


@task(name="upsert_cdm")
def task_upsert(source_id: str, indicator_id: str, cdm_records: list) -> int:
    """Upsert CDMRecords to cdm.indicator_observation (idempotent, ON CONFLICT)."""
    from pipeline.db.warehouse import upsert_to_cdm

    log = get_run_logger()
    n = upsert_to_cdm(cdm_records)
    log.info("[%s/%s] Upserted %d CDM rows", source_id, indicator_id, n)
    return n


@task(name="publish_to_ckan", retries=2, retry_delay_seconds=30)
def task_publish(source_id: str, indicator_config: dict, record_count: int) -> None:
    """Publish or update a CKAN dataset entry for this indicator."""
    log = get_run_logger()
    published = publish_indicator_to_ckan(source_id, indicator_config, record_count)
    if published:
        log.info("[%s/%s] Published to CKAN", source_id, indicator_config["id"])
    else:
        log.info("[%s/%s] CKAN publish skipped (no API key)", source_id, indicator_config["id"])


@task(name="update_manifest")
def task_update_manifest(
    source_id: str,
    indicator_config: dict,
    df: pd.DataFrame,
    row_count: int,
    status: str = "success",
    error_message: str | None = None,
) -> None:
    """Persist the new watermark to cdm.ingest_manifest after a successful run."""
    from pipeline.db.warehouse import update_manifest

    new_watermark = _extract_watermark(df, indicator_config)
    update_manifest(
        source_system=source_id,
        source_key=indicator_config["id"],
        last_period=new_watermark,
        row_count=row_count,
        status=status,
        error_message=error_message,
    )


@flow(
    name="ingest",
    description="Generic data ingestion flow."
)
def ingest_flow(
    source_id: str,
    start_period: str | None = None,
) -> dict:
    """Run the full ingestion pipeline for all indicators of a registered source.

    Args:
        source_id:    Which source to ingest (must be in SOURCE_REGISTRY).
        start_period: Backfill override. Ignores the watermark and fetches from
                      this period onward. e.g. '2020', '2020Q1', '2020-01'.
                      Leave None for normal incremental mode.

    Returns:
        Summary dict: {indicator_id: {status, rows, watermark}} per indicator.
    """
    from pipeline.db.warehouse import log_run_finish, log_run_start, run_schema_migrations

    log = get_run_logger()
    log.info("=== Ingest flow: source=%s start_period=%s ===", source_id, start_period)

    # Ensure CDM schema exists (idempotent — safe to call on every run)
    run_schema_migrations()

    source_config = get_source_config(source_id)
    indicators    = source_config["indicators"]
    run_id        = log_run_start("ingest", source_id)

    summary:      dict[str, dict] = {}
    total_staged: int = 0
    total_cdm:    int = 0

    try:
        for indicator_config in indicators:
            indicator_id = indicator_config["id"]
            log.info("── [%s] %s ──", source_id, indicator_id)

            try:
                raw_df = cast(pd.DataFrame, task_fetch(source_id, indicator_config, start_period))

                if raw_df.empty:
                    log.info("[%s/%s] No new data — skipping.", source_id, indicator_id)
                    task_update_manifest(source_id, indicator_config, raw_df, 0)
                    summary[indicator_id] = {"status": "skipped", "rows": 0}
                    continue

                clean_df = task_validate(source_id, indicator_config, raw_df)

                n_staged = task_stage(source_id, indicator_config, clean_df)
                total_staged += n_staged

                cdm_records = task_transform(source_id, indicator_config, clean_df)

                n_cdm = task_upsert(source_id, indicator_id, cdm_records)
                total_cdm += n_cdm

                task_publish(source_id, indicator_config, n_cdm)

                task_update_manifest(source_id, indicator_config, clean_df, n_cdm)

                summary[indicator_id] = {
                    "status": "success",
                    "rows":   n_cdm,
                }
                log.info("✅ [%s/%s] %d rows upserted", source_id, indicator_id, n_cdm)

            except Exception as exc:
                log.error("❌ [%s/%s] Failed: %s", source_id, indicator_id, exc, exc_info=True)
                task_update_manifest(
                    source_id, indicator_config, pd.DataFrame(), 0,
                    status="failed", error_message=str(exc),
                )
                summary[indicator_id] = {"status": "failed", "error": str(exc)}

        log_run_finish(run_id, "success", rows_staged=total_staged, rows_cdm=total_cdm)
        log.info(
            "=== Flow complete [%s]: %d staged / %d CDM rows ===",
            source_id, total_staged, total_cdm,
        )

    except Exception as exc:
        log.error("Flow-level failure [%s]: %s", source_id, exc, exc_info=True)
        log_run_finish(run_id, "failed", error_message=str(exc))
        raise

    return summary


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _extract_watermark(df: pd.DataFrame, indicator_config: dict) -> str | None:
    """Extract the maximum period value from a DataFrame as the new watermark.

    For file-based sources (CBN), stores 'hash:<sha256>' instead.
    For API sources, stores the max period string found in the data.
    """
    # File-based: watermark is the file hash stored by the connector
    file_hash = indicator_config.get("_file_hash")
    if file_hash:
        return f"hash:{file_hash}"

    # API-based: find the max period column
    if df.empty:
        return None

    for col in ("TIME_PERIOD", "Year", "year", "Period", "Date"):
        if col in df.columns:
            try:
                return str(df[col].dropna().astype(str).max())
            except Exception:
                pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Run ingestion for a specific source")
    parser.add_argument("source_id", help="Source ID from SOURCE_REGISTRY (e.g. CBN, NigeriaDataPortal)")
    parser.add_argument("--start-period", default=None, help="Backfill from this period (e.g. 2020, 2020Q1)")
    args = parser.parse_args()

    result = ingest_flow(args.source_id, start_period=args.start_period)
    print(result)
    sys.exit(0 if all(v.get("status") != "failed" for v in result.values()) else 1)
