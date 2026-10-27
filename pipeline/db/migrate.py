"""Versioned migrations. Run explicitly before deployment, never from a request."""
from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import text


def migrate(engine) -> list[str]:
    applied = []
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(719640211)"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS cdm"))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS cdm.schema_migrations
            (version TEXT PRIMARY KEY, sha256 TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"""))
        for path in sorted((Path(__file__).parent / "migrations").glob("*.sql")):
            sql = path.read_text()
            digest = hashlib.sha256(sql.encode()).hexdigest()
            previous = conn.execute(text("SELECT sha256 FROM cdm.schema_migrations WHERE version=:v"), {"v": path.stem}).scalar()
            if previous:
                if previous != digest:
                    raise RuntimeError(f"Previously applied migration changed: {path.name}")
                continue
            conn.execute(text(sql))
            if path.stem == "0002_publisher_portal":
                # Preserve old tokens and ownership, but authenticate by hash henceforth.
                rows = conn.execute(text("SELECT id, api_key FROM cdm.publishers WHERE api_key IS NOT NULL AND api_key <> ''")).all()
                for publisher_id, key in rows:
                    conn.execute(text("""INSERT INTO cdm.portal_integration_tokens
                        (publisher_id,name,token_hash,scopes,legacy)
                        VALUES (:p,'Existing publisher integration',:h,
                        '["sources:write","uploads:write","ingest:trigger","datasets:read"]'::jsonb,true)
                        ON CONFLICT(token_hash) DO NOTHING"""),
                        {"p": publisher_id, "h": hashlib.sha256(key.encode()).hexdigest()})
            conn.execute(text("INSERT INTO cdm.schema_migrations(version,sha256) VALUES (:v,:h)"), {"v": path.stem, "h": digest})
            applied.append(path.stem)
    return applied


if __name__ == "__main__":
    from pipeline.db.warehouse import get_engine
    print("Applied:", migrate(get_engine()))
