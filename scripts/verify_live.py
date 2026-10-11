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


def check_world_bank_databases() -> list[dict]:
    """Beyond the main database: does each extra one list indicators and hold Nigeria data?"""
    cfg = source("WorldBank")
    connector = WorldBankConnector(config={**cfg, "options": {**cfg["options"], "request_delay_seconds": 0.3}})
    rows: list[dict] = []
    seen: set[str] = set()
    for database in connector.databases():
        label = f"{database['id']} {database.get('name', '')}"
        try:
            listed = connector.discover_database(database)
        except Exception as exc:
            rows.append({"check": label, "status": FAIL, "detail": f"cannot list: {str(exc)[:160]}"})
            continue
        fresh = [i for i in listed if i["dataset_id"] not in seen]
        seen.update(i["dataset_id"] for i in listed)
        if int(database["id"]) == 2:
            rows.append({"check": label, "status": OK, "detail": f"{len(listed)} indicators (checked one by one above)"})
            continue
        step = max(1, len(fresh) // 8)
        with_data, errors, periods = 0, [], []
        sample = fresh[::step][:8]
        for indicator in sample:
            try:
                df = connector.fetch(indicator)
                if not df.empty:
                    with_data += 1
                    periods.append(str(df.iloc[-1]["TIME_PERIOD"]))
            except Exception as exc:
                errors.append(f"{indicator['dataset_id']}: {str(exc)[-90:]}")
        status = FAIL if errors and not with_data else (OK if with_data else WARN)
        detail = (f"{len(listed)} indicators, {len(fresh)} not in an earlier database; "
                  f"{with_data} of {len(sample)} sampled have Nigeria data"
                  + (f", latest periods {sorted(set(periods))[-3:]}" if periods else "")
                  + (f"; errors: {errors[:2]}" if errors else ""))
        rows.append({"check": label, "status": status, "detail": detail})
    return rows


def check_dmo() -> list[dict]:
    """Read every state-debt document the DMO lists, as the pipeline would."""
    from pipeline.connectors.dmo import DMOConnector
    from pipeline.geo import STATES

    cfg = source("DMO")
    connector = DMOConnector(config=cfg)
    rows: list[dict] = []
    try:
        documents = connector.discover()
    except Exception as exc:
        return [{"check": "DMO document list", "status": FAIL, "detail": f"{type(exc).__name__}: {str(exc)[:200]}"}]
    if not documents:
        return [{"check": "DMO document list", "status": FAIL, "detail": "no domestic-debt documents found on the page"}]
    rows.append({"check": "DMO document list", "status": OK,
                 "detail": f"{len(documents)} quarterly documents, {documents[-1]['period']} to {documents[0]['period']}"})

    from pipeline.connectors.dmo import document_text

    accepted, with_gaps, rejected, raw = [], [], [], []
    newest_detail = ""
    # A sample is enough to know the reader still works, and is kinder to the
    # DMO's server than fetching every document on every check: the three
    # newest quarters, one from the middle and the oldest.
    sample = documents[:3] + [documents[len(documents) // 2], documents[-1]] if len(documents) > 5 else documents
    for document in sample:
        try:
            amounts, total = connector.read_document(document)
        except Exception as exc:
            rejected.append(f"{document['period']}: {str(exc).split(': ', 1)[-1][:150]}")
            if len(raw) < 3:       # show how the text of a few failures actually reads
                try:
                    content = connector._http_get(document["file_url"]).content
                    lines = [" ".join(l.split()) for l in document_text(content).splitlines()]
                    wanted = [l for l in lines if any(k in l.upper() for k in ("LAGOS", "TOTAL", "KANO", "NIGER"))][:6]
                    raw.append(f"{document['period']} ({content[:5]!r}, {len(lines)} lines): " + " // ".join(wanted))
                except Exception as inner:
                    raw.append(f"{document['period']}: could not re-read ({inner})")
            continue
        (accepted if len(amounts) == len(STATES) else with_gaps).append(document["period"])
        if not newest_detail:
            top = sorted(amounts.items(), key=lambda kv: -kv[1])[:3]
            newest_detail = (f"{document['period']}: {len(amounts)} states, sum {sum(amounts.values()):,.2f}, "
                             f"stated total {total if total is None else format(total, ',.2f')}; "
                             f"largest {[(STATES[c], round(v / 1e9, 1)) for c, v in top]} (billions of naira)")
    rows.append({"check": "DMO newest accepted quarter", "status": OK if newest_detail else FAIL, "detail": newest_detail or "none"})
    rows.append({"check": f"DMO quarters accepted of {len(sample)} sampled (figures add up to the document's total)",
                 "status": OK if accepted else FAIL, "detail": f"{len(accepted)}: {', '.join(sorted(accepted))}"})
    if with_gaps:
        rows.append({"check": "DMO quarters accepted, document omits a state", "status": WARN, "detail": ", ".join(sorted(with_gaps))})
    if rejected:
        rows.append({"check": "DMO quarters left out", "status": WARN if accepted else FAIL,
                     "detail": f"{len(rejected)}: " + " ;; ".join(rejected)})
        for item in raw:
            rows.append({"check": "DMO raw text of a failure", "status": WARN, "detail": item[:700]})
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
        ("World Bank databases", check_world_bank_databases()),
        ("Debt Management Office (state debt documents)", check_dmo()),
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
