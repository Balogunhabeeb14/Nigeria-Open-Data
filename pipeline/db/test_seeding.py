"""
Standalone verification script for seed_sources and pipeline config.
Tests that schema + seeding work, configs load, connectors/transforms resolve,
and the fallback mechanism operates correctly — all without Prefect.
"""
from __future__ import annotations
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(name)s — %(message)s")
logger = logging.getLogger("test_seeding")

PASS = 0
FAIL = 0

def check(label: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {label}")
    else:
        FAIL += 1
        print(f"  ❌ {label} — {detail}")


def main():
    global PASS, FAIL

    # ── Test 1: Schema migrations + auto-seed ─────────────────────────────
    print("\n=== Test 1: Schema Migrations + Auto-Seed ===")
    try:
        from pipeline.db.warehouse import run_schema_migrations
        run_schema_migrations()
        check("run_schema_migrations() succeeded", True)
    except Exception as e:
        check("run_schema_migrations() succeeded", False, str(e))

    # ── Test 2: list_source_ids returns seeded sources from DB ────────────
    print("\n=== Test 2: list_source_ids() ===")
    try:
        from pipeline.config import list_source_ids
        ids = list_source_ids()
        print(f"  Sources found: {ids}")
        check("NigeriaDataPortal in sources", "NigeriaDataPortal" in ids)
        check("CBN in sources", "CBN" in ids)
        check("NBS_Reports in sources", "NBS_Reports" in ids)
    except Exception as e:
        check("list_source_ids() succeeded", False, str(e))

    # ── Test 3: get_source_config loads each source correctly ─────────────
    print("\n=== Test 3: get_source_config() ===")
    from pipeline.config import get_source_config

    for sid, expected_mode, expected_connector_suffix in [
        ("NigeriaDataPortal", "api",      "NigeriaDataPortalConnector"),
        ("CBN",               "file",     "CBNConnector"),
        ("NBS_Reports",       "document", "GenericFileConnector"),
    ]:
        try:
            cfg = get_source_config(sid)
            check(f"{sid} loads", True)
            check(f"{sid} ingest_mode={expected_mode}", cfg["ingest_mode"] == expected_mode, f"got {cfg['ingest_mode']}")
            check(f"{sid} connector ends with {expected_connector_suffix}", cfg["connector"].endswith(expected_connector_suffix), f"got {cfg['connector']}")
            check(f"{sid} has indicators", len(cfg.get("indicators", [])) > 0, f"got {cfg.get('indicators', [])}")
        except Exception as e:
            check(f"{sid} loads", False, str(e))

    # ── Test 4: Connectors and transforms can be imported ─────────────────
    print("\n=== Test 4: Connector + Transform Import ===")
    from pipeline.registry import source_registry

    for sid in ["NigeriaDataPortal", "CBN", "NBS_Reports"]:
        try:
            connector = source_registry.get_connector(sid)
            check(f"{sid} connector instantiates", connector is not None)
        except Exception as e:
            check(f"{sid} connector instantiates", False, str(e))

        try:
            transform_fn = source_registry.get_transform(sid)
            check(f"{sid} transform is callable", callable(transform_fn))
        except Exception as e:
            check(f"{sid} transform is callable", False, str(e))

    # ── Test 5: Idempotency — re-run seed and verify no duplication ───────
    print("\n=== Test 5: Idempotent Re-Seed ===")
    try:
        from pipeline.db.seed_sources import seed_default_sources
        count1 = seed_default_sources()
        count2 = seed_default_sources()
        ids_after = list_source_ids()
        check("Re-seed returns same count", count1 == count2, f"first={count1}, second={count2}")
        check("No duplicate source_ids", len(ids_after) == len(set(ids_after)), f"ids={ids_after}")
    except Exception as e:
        check("Idempotent re-seed", False, str(e))

    # ── Test 6: Fallback when DB is unavailable ───────────────────────────
    print("\n=== Test 6: Code Fallback (simulated) ===")
    try:
        from pipeline.db.seed_sources import DEFAULT_SOURCES
        fallback_ids = [s["source_id"] for s in DEFAULT_SOURCES]
        check("DEFAULT_SOURCES importable", len(fallback_ids) > 0)
        check("NigeriaDataPortal in fallback", "NigeriaDataPortal" in fallback_ids)
        check("CBN in fallback", "CBN" in fallback_ids)
    except Exception as e:
        check("Fallback import", False, str(e))

    # ── Test 7: Verify DB rows directly ───────────────────────────────────
    print("\n=== Test 7: Direct DB Verification ===")
    try:
        from pipeline.db.warehouse import get_engine
        from sqlalchemy import text
        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT source_id, ingest_mode, is_active FROM cdm.data_sources ORDER BY source_id")).fetchall()
            print(f"  DB rows: {[(r[0], r[1], r[2]) for r in rows]}")
            check("3 active sources in DB", len(rows) == 3, f"got {len(rows)}")
            for r in rows:
                check(f"{r[0]} is_active=True", r[2] is True, f"is_active={r[2]}")
    except Exception as e:
        check("Direct DB query", False, str(e))

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n{'='*50}")
    print(f"RESULTS: {PASS} passed, {FAIL} failed")
    print(f"{'='*50}")
    sys.exit(1 if FAIL > 0 else 0)


if __name__ == "__main__":
    main()
