"""Event-driven file watcher for the landing zone.

Scans landing folders for new/changed files (via SHA-256), triggering ingest_flow for updates.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from prefect import flow, get_run_logger, task

from pipeline.settings import settings

logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS = frozenset({".csv", ".xlsx", ".xls", ".json", ".parquet"})


# ── Manifest helpers ──────────────────────────────────────────────────────────

def _ensure_watcher_table(conn) -> None:
    from sqlalchemy import text
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS cdm.file_watcher_manifest (
            file_path    TEXT        PRIMARY KEY,
            file_hash    TEXT        NOT NULL,
            source_id    TEXT        NOT NULL,
            processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))


def _get_known_hashes(conn) -> dict[str, str]:
    from sqlalchemy import text
    rows = conn.execute(
        text("SELECT file_path, file_hash FROM cdm.file_watcher_manifest")
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def _mark_processed(conn, file_path: str, file_hash: str, source_id: str) -> None:
    from sqlalchemy import text
    conn.execute(text("""
        INSERT INTO cdm.file_watcher_manifest (file_path, file_hash, source_id)
        VALUES (:path, :hash, :source)
        ON CONFLICT (file_path) DO UPDATE SET
            file_hash    = EXCLUDED.file_hash,
            source_id    = EXCLUDED.source_id,
            processed_at = NOW()
    """), {"path": file_path, "hash": file_hash, "source": source_id})


def _compute_hash(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


# ── Tasks ─────────────────────────────────────────────────────────────────────

@task(name="scan_landing_zone")
def scan_landing_zone() -> list[dict]:
    """Scan all source landing folders for new or changed files.

    Returns a list of file change events:
        {"file_path": str, "source_id": str, "file_hash": str, "is_new": bool}
    """
    from pipeline.db.warehouse import get_engine

    log = get_run_logger()
    engine = get_engine()
    changes: list[dict] = []

    with engine.begin() as conn:
        _ensure_watcher_table(conn)
        known = _get_known_hashes(conn)

        from pipeline.config import list_source_ids, get_source_config

        for source_id in list_source_ids():
            source_cfg = get_source_config(source_id)
            folder     = settings.landing_root / source_cfg["landing_dir"]

            if not folder.exists():
                continue

            for file_path in sorted(folder.iterdir()):
                if file_path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
                    continue

                abs_path     = str(file_path.resolve())
                current_hash = _compute_hash(file_path)
                is_new       = abs_path not in known
                has_changed  = not is_new and known[abs_path] != current_hash

                if is_new or has_changed:
                    label = "new" if is_new else "changed"
                    log.info("File %s detected: %s/%s", label, source_id, file_path.name)
                    changes.append({
                        "file_path":  abs_path,
                        "source_id":  source_id,
                        "file_hash":  current_hash,
                        "is_new":     is_new,
                        "filename":   file_path.name,
                    })

    log.info("File watcher: %d new/changed file(s) found", len(changes))
    return changes


@task(name="trigger_source_ingestion")
def trigger_source_ingestion(file_info: dict) -> dict:
    """Run ingest_flow for the source that owns the changed file."""
    from pipeline.db.warehouse import get_engine
    from pipeline.flows.ingest_flow import ingest_flow

    log     = get_run_logger()
    source_id = file_info["source_id"]
    filename  = file_info["filename"]
    result    = {"file": filename, "source": source_id, "status": "unknown"}

    log.info("Triggering ingest_flow for %s (file: %s)", source_id, filename)
    try:
        ingest_flow(source_id)
        result["status"] = "success"

        # Mark file as processed in watcher manifest
        engine = get_engine()
        with engine.begin() as conn:
            _ensure_watcher_table(conn)
            _mark_processed(conn, file_info["file_path"], file_info["file_hash"], source_id)

        log.info("✅ Ingestion complete for %s/%s", source_id, filename)

    except Exception as exc:
        log.error("❌ Ingestion failed for %s/%s: %s", source_id, filename, exc, exc_info=True)
        result["status"] = "failed"
        result["error"]  = str(exc)

    return result


# ── Flow ──────────────────────────────────────────────────────────────────────

@flow(
    name="file_watcher",
    description=(
        "Scans data/raw/ every 15 minutes for new or changed files. "
        "Triggers source-specific ingestion for any changes detected via SHA-256 comparison."
    ),
)
def file_watcher_flow() -> dict:
    """Poll all landing zone folders and trigger ingestion for any new/changed files."""
    log = get_run_logger()
    log.info("=== File Watcher: scanning landing zone ===")

    changes = scan_landing_zone()

    if not changes:
        log.info("No changes detected. Nothing to do.")
        return {"files_processed": 0, "triggered": 0, "failed": 0}

    # Deduplicate by source_id — don't trigger the same source twice
    # if multiple files in the same landing folder changed simultaneously
    seen_sources: set[str] = set()
    unique_changes = []
    for change in changes:
        if change["source_id"] not in seen_sources:
            unique_changes.append(change)
            seen_sources.add(change["source_id"])

    results = [trigger_source_ingestion(ch) for ch in unique_changes]

    triggered = sum(1 for r in results if r["status"] == "success")
    failed    = sum(1 for r in results if r["status"] == "failed")

    log.info(
        "=== File Watcher complete: %d source(s) triggered, %d failed ===",
        triggered, failed,
    )
    return {
        "files_processed": len(changes),
        "triggered":       triggered,
        "failed":          failed,
    }


if __name__ == "__main__":
    file_watcher_flow()
