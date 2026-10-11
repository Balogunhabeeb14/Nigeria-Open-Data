# Naija Open Data

Naija Open Data is an independent, open-source platform that collects public data about Nigeria from many sources and republishes it in one searchable catalogue, with every dataset's source, licence, coverage and last refresh shown.

It is a volunteer project. It is not a government service.

---

## What it does

| | How | Where |
|---|---|---|
| **Loads indicator data** | Connectors pull time series, normalise them into one common table and publish each series to CKAN as a full, downloadable, queryable table | `pipeline/connectors`, `pipeline/transforms`, `pipeline/publisher.py` |
| **Lists other portals' datasets** | A harvester copies catalogue entries (not files) from other CKAN portals, crediting the original publisher | `pipeline/harvest` |
| **Tracks every source** | One catalogue of sources in use, planned, link-only and excluded | `data_sources/catalog.yaml` |

### Sources today

| Source | Status | Notes |
|---|---|---|
| World Bank, World Development Indicators | Live | 21 featured indicators plus the rest of the WDI catalogue (1,498 series listed) through discovery |
| Humanitarian Data Exchange, openAFRICA, EnergyData.info | Harvested | About 370 Nigeria datasets listed with links to the original files |
| CBN Statistics | Switched off | Connector present; the seeded file links return 404 and need replacing |
| Nigeria Data Portal (Open Data for Africa) | Switched off | Connector present; the seeded dataset ids are placeholders the API rejects |

`data_sources/catalog.yaml` lists 40 sources with access method, licence, priority and what has been verified.

---

## System architecture

```mermaid
graph TD
    User[User browser] <--> Frontend[Next.js frontend]
    Frontend <--> |REST API| CKAN[CKAN catalogue + DataStore]

    subgraph Pipeline ["Ingestion pipeline (Prefect)"]
        direction TB
        Scheduler[Schedules] --> Ingest[ingest flow]
        Watcher[File watcher, 15 min] --> Ingest
        Scheduler --> Harvest[harvest flow]
        Ingest --> Conn[Connectors: World Bank, CBN, Nigeria Data Portal, file drop]
        Conn --> QC[Quality checks]
        QC --> CDM[(Pipeline DB: cdm.indicator_observation)]
        CDM --> Pub[Publisher: full table per indicator]
    end

    Pub --> CKAN
    Harvest --> |catalogue entries only| CKAN
    Conn <--> WB[api.worldbank.org]
    Conn <--> CBNSite[statistics.cbn.gov.ng]
    Harvest <--> Portals[HDX / openAFRICA / EnergyData.info]
    CKAN <--> Solr[Solr] & CKANDb[(CKAN DB)]
```

### How a run stays dependable

| Behaviour | What happens |
|---|---|
| **One failure is contained** | Each indicator has its own manifest row (`cdm.ingest_manifest`) with status and error. A failing indicator never stops the others. |
| **Unchanged data is skipped** | The fetched rows are hashed. If the hash matches the last good run and the dataset is already on the portal, nothing is rewritten. |
| **Revisions are picked up** | Sources that revise history (World Bank) are fetched whole each run; rows are upserted, so revised values replace old ones and nothing is duplicated. |
| **The portal catches up** | A failed CKAN publish is recorded and retried on the next run even if the data has not changed. Data loaded before CKAN was configured is published once it is. |
| **A dead source stops the run** | After 5 failures in a row (configurable) the run stops instead of retrying hundreds of indicators. The next scheduled run resumes. |
| **Runs are idempotent** | Unique key `(source_system, indicator_id, geo_code, period)`; re-running never creates duplicates. |

---

## Folder structure

```
Nigeria-Open-Data/
├── data_sources/
│   └── catalog.yaml               # Every source: in use, planned, link-only, excluded
│
├── pipeline/
│   ├── api.py                     # FastAPI: publisher registration, uploads, read endpoints
│   ├── scrape.py                  # FastAPI routes that trigger ingestion on demand
│   ├── config.py                  # Reads source configuration from cdm.data_sources
│   ├── registry.py                # Loads connector and transform classes by dotted path
│   ├── publisher.py               # Publishing: dataset + full data table (CKAN or built-in)
│   ├── bootstrap.py               # Standalone loader: fills and refreshes the catalogue
│   ├── catalog/
│   │   ├── local.py               # Built-in catalogue, driven like a CKAN client
│   │   └── api.py                 # Its read API, in CKAN's shape
│   ├── deploy.py                  # Registers Prefect schedules
│   ├── settings.py                # Environment configuration (pydantic-settings)
│   ├── security.py                # Admin token and input checks for the API
│   │
│   ├── connectors/
│   │   ├── base.py                # BaseConnector: HTTP retries, hashing, expand_indicators()
│   │   ├── world_bank.py          # World Bank Indicators API, with catalogue discovery
│   │   ├── cbn.py                 # CBN Excel downloads
│   │   ├── nigeria_data_portal.py # Open Data for Africa API + CSV fallback
│   │   ├── generic.py             # CSV / Excel / PDF files dropped in the landing zone
│   │   └── s3.py                  # Object storage client
│   │
│   ├── transforms/                # Raw rows → CDMRecord
│   │   ├── cdm.py                 # The common data model
│   │   └── *_transform.py
│   │
│   ├── harvest/
│   │   ├── portals.py             # Which CKAN portals to harvest, filtered to Nigeria
│   │   └── ckan_harvester.py      # Remote package_search → our catalogue
│   │
│   ├── flows/
│   │   ├── ingest_flow.py         # fetch → validate → stage → transform → upsert → publish
│   │   ├── harvest_flow.py        # Weekly catalogue harvest
│   │   └── file_watcher_flow.py   # Every 15 minutes: new files in the landing zone
│   │
│   ├── quality/checks.py          # Row count, nulls, duplicates, value range
│   ├── db/
│   │   ├── schema.sql             # Tables and additive migrations (idempotent)
│   │   ├── warehouse.py           # Database helpers
│   │   └── seed_sources.py        # Default source definitions
│   └── tests/                     # pytest suite (no network needed)
│
├── datapipeline/                  # Earlier Mage AI experiment; not used by the pipeline
├── src/                           # Next.js frontend
├── scripts/
│   ├── run_local.sh               # Run everything without Docker
│   └── verify_live.py             # Ask every real source for data and report
├── docker-compose.lite.yml        # 2 containers: Postgres + app (built-in catalogue)
├── docker-compose.yml             # Full stack with CKAN, Solr, Redis, Prefect
├── .env.example
└── .github/workflows/             # tests.yml (pytest), ingest.yml (scheduled ingestion)
```

---

## Common Data Model (CDM)

Every indicator from every source is normalised into a single table:

```sql
-- cdm.indicator_observation (one row = one data point)
source_system   TEXT    -- 'WorldBank' | 'CBN' | 'NigeriaDataPortal' | <uploaded source id>
domain          TEXT    -- 'economy' | 'health' | 'education' | 'energy' | ...
indicator_id    TEXT    -- 'WB_NY_GDP_MKTP_CD' | 'CBN_INTEREST_MPR'
indicator_name  TEXT    -- human-readable name
geo_level       TEXT    -- 'national' | 'state' | 'lga'
geo_code        TEXT    -- 'NG' | 'NG-LA'
geo_name        TEXT    -- 'Nigeria' | 'Lagos'
period_type     TEXT    -- 'year' | 'quarter' | 'month'
period          TEXT    -- '2024' | '2024Q1' | '2024-01'
value           NUMERIC
unit            TEXT
raw_source_url  TEXT    -- where this number can be checked
last_updated_at TIMESTAMPTZ
```

### What reaches CKAN

One indicator becomes one CKAN dataset (for example `ng-wb-ny-gdp-mktp-cd`) with:

- a **DataStore resource** holding the full table, so download (`/datastore/dump/<id>`), the query API (`datastore_search`) and table preview all work;
- **provenance**: source name and link, licence, unit, period covered, row count, last refresh;
- a **topic** (CKAN group) from the indicator's domain.

---

## Try it: the whole app in one command

```bash
docker compose -f docker-compose.lite.yml up --build
# then open http://localhost:3000
```

This starts two containers: Postgres, and one app container with the website, the API and a loader. No CKAN, Solr, Redis or Prefect server is needed. The same command works in a GitHub Codespace (open port 3000 when it is offered).

On first start the loader fills the catalogue in this order, and the site shows datasets as they arrive:

1. the 21 featured World Bank indicators (under a minute);
2. Nigeria datasets listed on HDX, openAFRICA and EnergyData.info;
3. the rest of the World Bank catalogue (about 1,500 requests; let it run).

It then refreshes weekly. Tune it with `BOOTSTRAP_FULL=false`, `BOOTSTRAP_HARVEST=false` or `REFRESH_HOURS` (see `pipeline/bootstrap.py`).

Without Docker, with Python 3.11+, Node 20+ and a Postgres database:

```bash
pip install -r pipeline/requirements.txt && npm ci
export PIPELINE_DB_URL=postgresql://user:password@localhost:5432/naija
scripts/run_local.sh
```

### Two ways to run the catalogue

| | Built-in catalogue (`CATALOG_BACKEND=local`) | CKAN (`CATALOG_BACKEND=ckan`, the default) |
|---|---|---|
| Start with | `docker-compose.lite.yml` | `docker-compose.yml` |
| Containers | 2 | 7 |
| Catalogue lives in | the pipeline database (`cdm.catalog_*`) | CKAN + Solr |
| Search | Postgres full-text search | Solr |
| Scheduling | built-in loader, weekly | Prefect deployments |
| Extras | none | CKAN admin UI, extensions, harvesting plugins |

The pipeline and the website are identical in both. The built-in catalogue answers the same API routes as CKAN (`/api/3/action/package_search`, `package_show`, `group_list`, `organization_list`, `datastore_search`, and `/datastore/dump/<id>` for CSV), so moving between them is a setting, not a rewrite.

Only the website's port is published in the lite set-up. The pipeline API stays inside the container because its write endpoints are not yet access-controlled; the website proxies the read-only routes.

---

## Getting started with the full CKAN stack

### 1. Configure

```bash
cp .env.example .env      # then set CKAN_API_KEY and the passwords
```

### 2. Run with Docker

```bash
docker-compose up -d
docker-compose logs -f pipeline
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| CKAN | http://localhost:5000 |
| Pipeline API | http://localhost:8000 |
| Prefect UI | http://localhost:4200 |
| Pipeline DB | localhost:5433 |

### 3. Load data by hand

```bash
# A quick first run: the featured World Bank indicators only
docker-compose exec pipeline_db psql -U pipeline -c \
  "UPDATE cdm.data_sources SET options = options || '{\"discover\": false}' WHERE source_id = 'WorldBank'"
docker-compose exec pipeline python -m pipeline.flows.ingest_flow WorldBank

# Everything the World Bank publishes for Nigeria (about 1,500 requests; allow time)
#   set "discover": true again, or cap it with "max_indicators": 200
docker-compose exec pipeline python -m pipeline.flows.ingest_flow WorldBank

# Check what other portals would add, without writing anything
docker-compose exec pipeline python -m pipeline.flows.harvest_flow --dry-run --limit 20

# Harvest for real
docker-compose exec pipeline python -m pipeline.flows.harvest_flow
```

Built-in sources are re-seeded from `seed_sources.py` at start-up. Two things you set in the database are kept: `is_active`, and any `options` keys (as in the `discover` example above).

### 4. Drop a file

Put a CSV or Excel file in `data/raw/<landing_dir>/`. The file watcher picks it up within 15 minutes.

### 5. Run the tests

```bash
pip install -r pipeline/requirements.txt pytest
docker run -d -p 5433:5432 -e POSTGRES_USER=pipeline -e POSTGRES_PASSWORD=pipeline \
    -e POSTGRES_DB=pipeline postgres:15-alpine
python -m pytest pipeline/tests -q
```

Sources and CKAN are faked, so no network is needed. Tests that need Postgres are skipped if it is not reachable.

---

## How to add a data source

First add it to `data_sources/catalog.yaml`, with its licence. Then:

**A portal that runs CKAN** needs no code: add an entry to `pipeline/harvest/portals.py`.

**An API or file source** takes three steps:

### Step 1: a connector, `pipeline/connectors/<name>.py`

```python
from pipeline.connectors.base import BaseConnector
import pandas as pd

class MyConnector(BaseConnector):
    source_id = "MySource"

    def discover(self) -> list[dict]:
        ...   # optional: list what the source offers

    def fetch(self, dataset_config: dict, since: str | None = None) -> pd.DataFrame:
        ...   # return raw rows; use self._http_get() for retries
```

Override `expand_indicators()` if the source can list its own series, as `WorldBankConnector` does. Coverage then grows without anyone editing a list.

### Step 2: a transform, `pipeline/transforms/<name>_transform.py`

```python
from pipeline.transforms.cdm import CDMRecord, infer_period_type

def transform(df, dataset_config) -> list[CDMRecord]:
    ...
```

### Step 3: a source definition in `pipeline/db/seed_sources.py`

```python
{
    "source_id": "MySource",
    "connector": "pipeline.connectors.my_source.MyConnector",
    "transform": "pipeline.transforms.my_source_transform.transform",
    "domain": "health",
    "schedule": "0 4 * * 1",
    "landing_dir": "my_source",
    "ingest_mode": "api",              # 'api' | 'file' | 'document'
    "options": {                       # shown to users on every dataset
        "source_name": "Publisher, dataset family",
        "source_url": "https://...",
        "license_id": "cc-by",         # a CKAN licence id, or omit if unknown
        "license_title": "Creative Commons Attribution 4.0 (CC BY 4.0)",
    },
    "indicators": [
        {"id": "MY_INDICATOR", "name": "Readable name (unit)", "dataset_id": "source-code", "domain": "health"},
    ],
}
```

If a source states no licence, leave the licence out. The dataset is then labelled "Not specified by the source" instead of being presented as open.

Add tests beside the others in `pipeline/tests/`; `fakes.py` has a CKAN stand-in and response builders.

---

## Schedules

| Deployment | When | What |
|---|---|---|
| `worldbank-ingestion` | Sundays 01:00 UTC | World Development Indicators |
| `nigeriadataportal-ingestion` | Daily 02:00 UTC | Open Data for Africa |
| `cbn-ingestion` | Mondays 03:00 UTC | CBN files |
| `catalogue-harvest` | Saturdays 05:00 UTC | HDX, openAFRICA, EnergyData.info |
| `file-watcher` | Every 15 minutes | New or changed files in the landing zone |

Backfill: `python -m pipeline.flows.ingest_flow <source> --start-period 2020`.

---

## Debugging

```sql
-- What happened in recent runs ('success' | 'partial' | 'failed')
SELECT flow_name, source_system, status, rows_cdm, error_message, started_at
FROM cdm.pipeline_run_log ORDER BY started_at DESC LIMIT 20;

-- Per indicator: data status, last period, and whether it reached the portal
SELECT source_system, source_key, status, last_period, row_count, publish_state, error_message
FROM cdm.ingest_manifest
WHERE status = 'failed' OR publish_state = 'failed';
```

The Prefect UI (http://localhost:4200) has per-task logs for each run.

---

## Checking it against the real world

Unit tests fake the sources. Two things check the real ones:

```bash
python scripts/verify_live.py     # asks every source for real data and reports what came back
```

and the **Live check** workflow (`.github/workflows/live-check.yml`), which runs that script and also builds the two-container app, starts it, waits for real datasets to load and fetches its pages, data API and CSV download. It runs every Monday, on demand, and when the pieces it covers change. A third job loads the entire World Bank catalogue; run it on demand or by putting `[full-check]` in a commit message.

The site's own **Data status** page (`/status`, from `GET /api/status`) shows, per source, how many datasets were loaded and when.

---

## Security

- **Reading is open.** The catalogue, the data API and downloads need no account.
- **Changing things needs the admin token.** Registering a publisher or source, uploading a file, triggering ingestion and listing publisher contacts all require the `X-Admin-Token` header. Until `ADMIN_API_TOKEN` is set on the server, those endpoints are switched off and answer 503.
- **Sources can only use code that ships with the pipeline.** A registered source names its connector and transform; anything outside `pipeline.connectors` and `pipeline.transforms` is refused.
- **Uploads are confined.** The file name is reduced to a safe one, only CSV, Excel and PDF up to 50 MB are accepted, and the file is stored only in the folder of a source the publisher owns.
- **In the lite set-up the pipeline API is not published at all.** Only the website's port is; it proxies the read-only routes.

```bash
curl -X POST http://localhost:8000/scrape/source/WorldBank -H "X-Admin-Token: $ADMIN_API_TOKEN"
```

---

## Known gaps

- CBN and Nigeria Data Portal start switched off: their seeded file links and dataset ids do not work (see the source catalogue). They are the route to more Nigerian-official and state-level data.
- The website's old publisher sign-up form is no longer linked; publishing by outside organisations needs a proper sign-in before it is offered again.
- The scheduled GitHub Action `ingest.yml` writes to a database that is discarded when the job ends, and has been failing; it predates this work.
- No usage analytics or feedback form yet.
- Charts cover one place over time. State and LGA tables are shown as tables; maps and multi-place charts are not built yet.
- The full CKAN stack (`docker-compose.yml`) has not been run end to end since these changes; the lite set-up is the tested path.

---

## Built with

- **Frontend**: Next.js 16 (TypeScript, React 19, Tailwind CSS)
- **Data catalogue**: CKAN 2.10 + DataStore, Apache Solr, Redis
- **Pipeline**: Python 3.11 (Pandas, SQLAlchemy, Requests, Tenacity), Prefect 3
- **Databases**: PostgreSQL 15 × 2 (CKAN, pipeline)
- **Infrastructure**: Docker Compose, GitHub Actions

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. For new data sources, add the source to `data_sources/catalog.yaml` and follow the guide above
4. Submit a pull request with a description of the source and indicators added

---

## License

MIT License. Hosted data is subject to the original source's terms of use.

---

## Contact

Questions, problems and dataset suggestions: [open an issue](https://github.com/Balogunhabeeb14/Nigeria-Open-Data/issues).
