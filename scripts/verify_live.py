#!/usr/bin/env python3
"""Check every configured data source against the real thing.

Needs internet, no database. Run it before a launch, after changing a source,
or on a schedule:

    python scripts/verify_live.py            # human-readable report
    python scripts/verify_live.py --markdown # for a CI job summary

For each source it reports what was actually received, so a wrong indicator
code, a moved file or a portal that refuses us is found here and not by a
user looking at an empty page.

Exit code: 1 if the World Bank source (the platform's core data) is failing
for more than a few indicators, else 0. Problems with other sources are
reported but do not fail the run.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("LANDING_ROOT", tempfile.mkdtemp(prefix="naija_verify_"))

from pipeline.connectors.world_bank import WorldBankConnector  # noqa: E402
from pipeline.db.seed_sources import DEFAULT_SOURCES  # noqa: E402
from pipeline.harvest import ckan_harvester  # noqa: E402
from pipeline.harvest.portals import HARVEST_PORTALS  # noqa: E402

OK, WARN, FAIL = "OK", "WARN", "FAIL"


def source(source_id: str) -> dict:
    return next(s for s in DEFAULT_SOURCES if s["source_id"] == source_id)


def check_world_bank() -> list[dict]:
    cfg = source("WorldBank")
    connector = WorldBankConnector(config={**cfg, "options": {**cfg["options"], "request_delay_seconds": 0.5}})
    rows: list[dict] = []

    try:
        catalogue = connector.discover()
        by_code = {c["dataset_id"]: c for c in catalogue}
        rows.append({"check": "World Bank catalogue", "status": OK if len(catalogue) > 1000 else WARN,
                     "detail": f"{len(catalogue)} indicators listed"})
    except Exception as exc:
        by_code = {}
        rows.append({"check": "World Bank catalogue", "status": FAIL, "detail": str(exc)[:200]})

    for indicator in cfg["indicators"]:
        code = indicator["dataset_id"]
        try:
            df = connector.fetch(indicator)
        except Exception as exc:
            rows.append({"check": code, "status": FAIL, "detail": str(exc)[:200]})
            continue
        if df.empty:
            rows.append({"check": code, "status": WARN, "detail": "valid code but no Nigeria data"})
            continue
        latest = df.iloc[-1]
        official = by_code.get(code, {}).get("name")
        detail = f"{len(df)} years, {df.iloc[0]['TIME_PERIOD']} to {latest['TIME_PERIOD']}, latest {latest['OBS_VALUE']:,.4g}"
        status = OK
        if by_code and code not in by_code:
            status, detail = WARN, detail + "; not in the WDI catalogue (retired or moved?)"
        elif official and official != indicator["name"]:
            detail += f'; official name is "{official}"'
        rows.append({"check": code, "status": status, "detail": detail})
    return rows


def check_harvest() -> list[dict]:
    rows = []
    for portal in HARVEST_PORTALS:
        try:
            page = ckan_harvester._search_page(portal, 0, 25)
            datasets = page.get("results") or []
            listable = [d for d in datasets if ckan_harvester.map_dataset(portal, d)]
            sample = "; ".join((d.get("title") or d.get("name") or "")[:50] for d in datasets[:3])
            status = OK if page.get("count") and listable else WARN
            rows.append({"check": f"{portal['id']} ({portal['base_url']})", "status": status,
                         "detail": f"{page.get('count')} datasets match; {len(listable)} of first {len(datasets)} listable. e.g. {sample}"})
        except Exception as exc:
            rows.append({"check": f"{portal['id']} ({portal['base_url']})", "status": FAIL, "detail": f"{type(exc).__name__}: {str(exc)[:200]}"})
        time.sleep(1)
    return rows


def check_files() -> list[dict]:
    """Sources that need hand-maintained URLs or ids: do the seeded ones still answer?"""
    import requests

    from pipeline.connectors.base import USER_AGENT
    rows = []
    for indicator in source("CBN")["indicators"]:
        url = indicator["excel_url"]
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30, stream=True)
            kind = resp.headers.get("content-type", "?")
            good = resp.status_code == 200 and "html" not in kind
            rows.append({"check": f"CBN {indicator['id']}", "status": OK if good else FAIL,
                         "detail": f"HTTP {resp.status_code}, {kind} — {url}"})
        except Exception as exc:
            rows.append({"check": f"CBN {indicator['id']}", "status": FAIL, "detail": f"{type(exc).__name__} — {url}"})
    for indicator in source("NigeriaDataPortal")["indicators"]:
        url = f"https://nigeria.opendataforafrica.org/api/1.0/data/{indicator['dataset_id']}"
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
            good = resp.status_code == 200 and "dataSets" in resp.text
            rows.append({"check": f"NigeriaDataPortal {indicator['id']}", "status": OK if good else FAIL,
                         "detail": f"HTTP {resp.status_code}: {resp.text[:90]!r}"})
        except Exception as exc:
            rows.append({"check": f"NigeriaDataPortal {indicator['id']}", "status": FAIL, "detail": type(exc).__name__})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--markdown", action="store_true", help="Print a Markdown report")
    args = parser.parse_args()

    sections = [
        ("World Bank (live source)", check_world_bank()),
        ("Portals harvested for listings", check_harvest()),
        ("Sources needing maintained links", check_files()),
    ]

    for title, rows in sections:
        if args.markdown:
            print(f"\n### {title}\n\n| Status | Check | What came back |\n|---|---|---|")
            for r in rows:
                print(f"| {r['status']} | `{r['check']}` | {r['detail'].replace('|', '/')} |")
        else:
            print(f"\n== {title} ==")
            for r in rows:
                print(f"  [{r['status']:4}] {r['check']}: {r['detail']}")

    wb = sections[0][1]
    wb_failures = sum(1 for r in wb if r["status"] == FAIL)
    totals = {s: sum(1 for _, rows in sections for r in rows if r["status"] == s) for s in (OK, WARN, FAIL)}
    print(f"\n{'**Totals:**' if args.markdown else 'Totals:'} {totals}")
    return 1 if wb_failures > 3 else 0


if __name__ == "__main__":
    sys.exit(main())
