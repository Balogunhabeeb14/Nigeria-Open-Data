"""Generic, parameterized data ingestion flow.

For every indicator of a registered source:

    fetch → (skip if unchanged) → validate → stage → transform → upsert → publish

Three rules keep it dependable:

* One indicator failing never stops the others. Each has its own manifest row
  with status and error message.
* Nothing is redone without reason. The fetched payload is hashed; if the hash
  matches the last good run and the dataset is already on the portal, the
  indicator is skipped.
* Data that reached the warehouse always reaches the portal eventually. A
  failed publish is recorded and retried on the next run, even when the data
  itself has not changed.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import cast

import pandas as pd
from prefect import flow, get_run_logger, task

from pipeline.config import get_source_config
from pipeline.publisher import FAILED, PUBLISHED, ckan_enabled, publish_indicator_to_ckan
from pipeline.quality.checks import QualityRunner
from pipeline.registry import source_registry

logger = logging.getLogger(__name__)

# Sources that are read whole each time (a downloaded or dropped file). For
# these the period watermark is not used as a filter: when the file changes,
# all of it is reprocessed so revised rows are picked up.
_FILE_MODES = frozenset({"file", "document"})


# ── Running with or without Prefect ───────────────────────────────────────────
# Under Prefect (the scheduled deployments) each step below is a tracked task.
# `run_ingest()` runs the very same steps as plain function calls, for places
# with no Prefect server: the standalone app's loader, scripts, notebooks.
_DIRECT: contextvars.ContextVar[bool] = contextvars.ContextVar("ingest_direct", default=False)


def _log():
    """The Prefect run logger when inside a run, else this module's logger."""
    if not _DIRECT.get():
        try:
            return get_run_logger()
        except Exception:
            pass
    return logger


def _run(step, *args):
    """Call a pipeline step: as a Prefect task, or directly with its retries."""
    if not _DIRECT.get():
        return step(*args)

    retries = int(step.retries or 0)
    delay = step.retry_delay_seconds or 0
    for attempt in range(retries + 1):
        try:
            return step.fn(*args)
        except Exception as exc:
            if attempt == retries:
                raise
            wait = delay[min(attempt, len(delay) - 1)] if isinstance(delay, (list, tuple)) else delay
            logger.warning("%s failed (%s); retry %d of %d in %ss", step.name, exc, attempt + 1, retries, wait)
            time.sleep(float(wait))


@dataclass
class FetchOutcome:
    """What one fetch produced. Passed between tasks explicitly."""

    df: pd.DataFrame
    content_hash: str | None = None
    file_meta: dict | None = None


def frame_hash(df: pd.DataFrame) -> str | None:
    """SHA-256 of a DataFrame's contents, independent of row order."""
    if df.empty:
        return None
    ordered = df.astype(str).sort_values(list(df.columns)).reset_index(drop=True)
    return hashlib.sha256(ordered.to_csv(index=False).encode("utf-8")).hexdigest()


# The connector already retries network errors with backoff, so the task-level
# retry is short. Long waits here multiply by the number of indicators.
@task(name="fetch_data", retries=2, retry_delay_seconds=15)
def task_fetch(
    source_id: str,
    indicator_config: dict,
    start_period: str | None,
    ingest_mode: str = "api",
) -> FetchOutcome:
    from pipeline.db.warehouse import get_watermark

    log = _log()
    indicator_id = indicator_config["id"]

    if start_period:
        since = start_period
    elif ingest_mode in _FILE_MODES:
        since = None
    else:
        since = get_watermark(source_id, indicator_id)
    log.info("[%s/%s] Fetching (since=%s)", source_id, indicator_id, since or "full history")

    # Connectors may attach '_file_hash' / '_file_meta' to the config they are
    # given. Hand them a private copy and read the result here, in the same
    # task, so nothing depends on a dict being shared across task boundaries.
    cfg = dict(indicator_config)
    connector = source_registry.get_connector(source_id)
    df = connector.fetch(cfg, since=since)
    log.info("[%s/%s] Fetched %d rows", source_id, indicator_id, len(df))

    # Hash the parsed rows, not the file bytes: a spreadsheet re-saved with
    # the same figures has different bytes but is not new data. The file's
    # own hash is the fallback when nothing tabular could be read from it.
    return FetchOutcome(
        df=df,
        content_hash=frame_hash(df) or cfg.get("_file_hash"),
        file_meta=cfg.get("_file_meta"),
    )


@task(name="validate_data")
def task_validate(
    source_id: str,
    indicator_config: dict,
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Run quality checks. Raises RuntimeError on CRITICAL failures (halts the task)."""
    log = _log()
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

    log = _log()
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
    log = _log()
    transform_fn = source_registry.get_transform(source_id)
    records = transform_fn(df, indicator_config)
    log.info("[%s/%s] Transformed %d CDM records", source_id, indicator_config["id"], len(records))
    return records


@task(name="upsert_cdm")
def task_upsert(source_id: str, indicator_id: str, cdm_records: list) -> int:
    """Upsert CDMRecords to cdm.indicator_observation (idempotent, ON CONFLICT)."""
    from pipeline.db.warehouse import upsert_to_cdm

    log = _log()
    n = upsert_to_cdm(cdm_records)
    log.info("[%s/%s] Upserted %d CDM rows", source_id, indicator_id, n)
    return n


@task(name="publish_to_ckan", retries=2, retry_delay_seconds=30)
def task_publish(source_id: str, indicator_config: dict, source_options: dict) -> str:
    """Publish the indicator's full table to CKAN. Returns the publish state.

    Raises on failure so Prefect retries; the flow records a final failure.
    """
    log = _log()
    state = publish_indicator_to_ckan(source_id, indicator_config, source_options=source_options)
    if state == PUBLISHED:
        log.info("[%s/%s] Published to the catalogue", source_id, indicator_config["id"])
    else:
        log.info("[%s/%s] Publish skipped (no catalogue configured)", source_id, indicator_config["id"])
    return state


@task(name="register_document")
def task_register_document(source_id: str, indicator_id: str, file_meta: dict | None) -> None:
    """Register the document metadata into cdm.dataset_registry."""
    from pipeline.db.warehouse import register_document

    log = _log()
    if file_meta:
        register_document(source_id, file_meta)
        log.info("[%s/%s] Registered document: %s", source_id, indicator_id, file_meta.get("file_name"))
    else:
        log.warning("[%s/%s] No document metadata found to register.", source_id, indicator_id)


def _publish_safely(source_id: str, indicator_config: dict, source_options: dict, log) -> str:
    """Publish and turn a final failure into a state instead of an exception."""
    try:
        return cast(str, _run(task_publish, source_id, indicator_config, source_options))
    except Exception as exc:
        log.error("[%s/%s] CKAN publish failed: %s", source_id, indicator_config["id"], exc)
        return FAILED


@flow(
    name="ingest",
    description="Generic data ingestion flow."
)
def ingest_flow(
    source_id: str,
    start_period: str | None = None,
    job_id: str | None = None,
    featured_only: bool = False,
) -> dict:
    """Run the full ingestion pipeline for all indicators of a registered source.

    Args:
        source_id:    Which source to ingest (a source_id in cdm.data_sources).
        start_period: Backfill override. Ignores the watermark and the
                      unchanged-data shortcut, and fetches from this period
                      onward. e.g. '2020', '2020Q1', '2020-01'.
                      Leave None for normal incremental mode.
        featured_only: Process just the indicators listed with the source and
                      skip discovery. A fast first pass before a full run.

    Returns:
        Summary dict: {indicator_id: {status, rows, ...}} per indicator.
        status is 'success', 'unchanged', 'skipped' (no data) or 'failed'.
    """
    if job_id:
        from pipeline.portal.processing import process_job
        result = process_job(source_id, job_id)
        if result.get("status") == "failed":
            raise RuntimeError(f"Publisher job failed: {result['error_code']}. See the dashboard.")
        return result

    from pipeline.db.warehouse import (
        get_manifest,
        log_run_finish,
        log_run_start,
        run_schema_migrations,
        update_manifest,
    )

    log = _log()
    log.info("=== Ingest flow: source=%s start_period=%s ===", source_id, start_period)

    # Ensure CDM schema exists (idempotent — safe to call on every run)
    run_schema_migrations()

    source_config = get_source_config(source_id)
    source_options = source_config.get("options") or {}
    ingest_mode = source_config.get("ingest_mode", "api")
    is_document = ingest_mode == "document"
    run_id = log_run_start("ingest", source_id)

    summary:      dict[str, dict] = {}
    total_staged: int = 0
    total_cdm:    int = 0

    try:
        # Connectors that can list what their source offers add to the
        # configured indicators here (see BaseConnector.expand_indicators).
        connector = source_registry.get_connector(source_id)
        indicators = (
            source_config["indicators"] if featured_only
            else connector.expand_indicators() or source_config["indicators"]
        )
        log.info("[%s] %d indicator(s) to process", source_id, len(indicators))

        # Circuit breaker: if a source fails this many indicators in a row
        # it is down or blocking us. Stop instead of grinding through (and
        # retrying) hundreds more; the next scheduled run picks them up.
        max_consecutive = int(source_options.get("max_consecutive_failures") or 5)
        consecutive_failures = 0
        not_attempted = 0

        for position, raw_config in enumerate(indicators):
            if consecutive_failures >= max_consecutive:
                not_attempted = len(indicators) - position
                log.error(
                    "[%s] %d indicators failed in a row. Stopping this run with %d not attempted.",
                    source_id, consecutive_failures, not_attempted,
                )
                break
            # Transforms and the publisher need to know which source they
            # are working for; the stored indicator config does not say.
            indicator_config = {**raw_config, "source_id": source_id}
            indicator_id = indicator_config["id"]
            log.info("── [%s] %s ──", source_id, indicator_id)

            try:
                previous = get_manifest(source_id, indicator_id) or {}
                outcome = cast(
                    FetchOutcome,
                    _run(task_fetch, source_id, indicator_config, start_period, ingest_mode),
                )
                raw_df = outcome.df
                # What gets published is the rows plus how they are described.
                # Folding the description in means a corrected name, unit or
                # licence is republished even when the numbers are the same.
                content_hash = _with_metadata(outcome.content_hash, indicator_config, source_options)

                if is_document:
                    _run(task_register_document, source_id, indicator_id, outcome.file_meta)

                if raw_df.empty:
                    log.info("[%s/%s] No tabular data extracted.", source_id, indicator_id)
                    update_manifest(source_id, indicator_id, None, previous.get("row_count") or 0)
                    summary[indicator_id] = {
                        "status": "success" if is_document else "skipped",
                        "rows": 0,
                    }
                    consecutive_failures = 0
                    continue

                unchanged = (
                    not start_period
                    and previous.get("status") == "success"
                    and content_hash is not None
                    and previous.get("content_hash") == content_hash
                )
                needs_publish = ckan_enabled() and previous.get("publish_state") != PUBLISHED

                if unchanged and not needs_publish:
                    log.info("[%s/%s] Unchanged since last run — skipped.", source_id, indicator_id)
                    update_manifest(source_id, indicator_id, None, previous.get("row_count") or 0)
                    summary[indicator_id] = {"status": "unchanged", "rows": 0}
                    consecutive_failures = 0
                    continue

                if unchanged:
                    # Data is already in the warehouse; only the portal is behind.
                    publish_state = _publish_safely(source_id, indicator_config, source_options, log)
                    update_manifest(
                        source_id, indicator_id, None, previous.get("row_count") or 0,
                        publish_state=publish_state,
                    )
                    summary[indicator_id] = {"status": "unchanged", "rows": 0, "publish": publish_state}
                    consecutive_failures = 0
                    continue

                clean_df = _run(task_validate, source_id, indicator_config, raw_df)

                n_staged = _run(task_stage, source_id, indicator_config, clean_df)
                total_staged += n_staged

                cdm_records = _run(task_transform, source_id, indicator_config, clean_df)

                n_cdm = _run(task_upsert, source_id, indicator_id, cdm_records)
                total_cdm += n_cdm

                publish_state = (
                    _publish_safely(source_id, indicator_config, source_options, log)
                    if n_cdm else previous.get("publish_state")
                )

                update_manifest(
                    source_system=source_id,
                    source_key=indicator_id,
                    last_period=_extract_watermark(clean_df),
                    row_count=n_cdm,
                    content_hash=content_hash,
                    publish_state=publish_state,
                )

                summary[indicator_id] = {
                    "status": "success",
                    "rows":   n_cdm,
                    "publish": publish_state,
                }
                log.info("✅ [%s/%s] %d rows upserted", source_id, indicator_id, n_cdm)
                consecutive_failures = 0

            except Exception as exc:
                log.error("❌ [%s/%s] Failed: %s", source_id, indicator_id, exc, exc_info=True)
                update_manifest(
                    source_id, indicator_id, None, 0,
                    status="failed", error_message=str(exc)[:2000],
                )
                summary[indicator_id] = {"status": "failed", "error": str(exc)}
                consecutive_failures += 1

        failed = sum(1 for v in summary.values() if v["status"] == "failed")
        problems = []
        if failed:
            problems.append(f"{failed} of {len(summary)} attempted indicators failed")
        if not_attempted:
            problems.append(f"run stopped early, {not_attempted} indicators not attempted")
        log_run_finish(
            run_id,
            "success" if not problems else ("failed" if failed == len(summary) else "partial"),
            rows_staged=total_staged,
            rows_cdm=total_cdm,
            error_message="; ".join(problems) or None,
        )
        log.info(
            "=== Flow complete [%s]: %d staged / %d CDM rows, %d failed ===",
            source_id, total_staged, total_cdm, failed,
        )

    except Exception as exc:
        log.error("Flow-level failure [%s]: %s", source_id, exc, exc_info=True)
        log_run_finish(run_id, "failed", error_message=str(exc))
        raise

    if failed:
        raise RuntimeError("One or more indicators failed; inspect the ingestion history")
    return summary


def run_ingest(
    source_id: str,
    start_period: str | None = None,
    featured_only: bool = False,
) -> dict:
    """Run the ingestion pipeline without Prefect. Same steps, same result.

    Nothing is orchestrated or recorded by Prefect; progress goes to the
    normal Python log and to cdm.pipeline_run_log / cdm.ingest_manifest.
    """
    token = _DIRECT.set(True)
    try:
        return ingest_flow.fn(source_id, start_period=start_period, featured_only=featured_only)
    finally:
        _DIRECT.reset(token)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

_DESCRIPTIVE_KEYS = ("name", "description", "unit", "domain", "source_organization", "featured", "source_url", "database")


def _with_metadata(data_hash: str | None, indicator_config: dict, source_options: dict) -> str | None:
    """Combine the data hash with a fingerprint of the published description."""
    if data_hash is None:
        return None
    described = {k: indicator_config.get(k) for k in _DESCRIPTIVE_KEYS}
    payload = json.dumps([data_hash, described, source_options], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _extract_watermark(df: pd.DataFrame) -> str | None:
    """Return the latest period in the data, used as the next run's `since`.

    Always a period, never a file hash: change detection for files lives in
    the manifest's content_hash column.
    """
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

def main() -> None:
    """`naija-ingest <source_id> [--start-period P]` (see pyproject.toml)."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Run ingestion for a specific source")
    parser.add_argument("source_id", help="Source ID in cdm.data_sources (e.g. WorldBank, CBN)")
    parser.add_argument("--start-period", default=None, help="Backfill from this period (e.g. 2020, 2020Q1)")
    parser.add_argument("--featured-only", action="store_true", help="Only the listed indicators; skip discovery")
    parser.add_argument("--no-prefect", action="store_true", help="Run directly, without a Prefect server")
    args = parser.parse_args()

    runner = run_ingest if args.no_prefect else ingest_flow
    result = runner(args.source_id, start_period=args.start_period, featured_only=args.featured_only)
    counts: dict[str, int] = {}
    for item in result.values():
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    print(f"{args.source_id}: {counts}")
    sys.exit(1 if counts.get("failed") else 0)


if __name__ == "__main__":
    main()
