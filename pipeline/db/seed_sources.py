"""
pipeline/db/seed_sources.py
===========================
Idempotently seeds baseline data sources into cdm.data_sources.
Supports structured (API/CSV/Excel) and unstructured (PDF/Document) configs.
"""
from __future__ import annotations

import json
import logging
from sqlalchemy import text
from pipeline.db.warehouse import get_engine

logger = logging.getLogger(__name__)

# ── Default Source Registry Configurations ────────────────────────────────────
DEFAULT_SOURCES = [
    {
        "source_id": "NigeriaDataPortal",
        "connector": "pipeline.connectors.nigeria_data_portal.NigeriaDataPortalConnector",
        "transform": "pipeline.transforms.nigeria_data_portal_transform.transform",
        "domain": "economics",
        "schedule": "0 2 * * *",       # Daily @ 02:00 UTC
        "landing_dir": "nigeria_data_portal",
        "ingest_mode": "api",
        "options": {
            "publisher_id": "open-data-for-africa",
            "publisher_title": "Open Data for Africa (African Development Bank)",
            "source_name": "Nigeria Data Portal, Open Data for Africa",
            "source_url": "https://nigeria.opendataforafrica.org/",
        },
        "indicators": [
            {
                "id": "GDP_REAL",
                "name": "Real Gross Domestic Product",
                "dataset_id": "NG_GDP_REAL",
                "domain": "economics",
                "unit": "Naira (Millions)",
            },
            {
                "id": "UNEMP_RATE",
                "name": "Unemployment Rate",
                "dataset_id": "NG_UNEMP_RATE",
                "domain": "economics",
                "unit": "%",
            },
        ],
    },
    {
        "source_id": "CBN",
        "connector": "pipeline.connectors.cbn.CBNConnector",
        "transform": "pipeline.transforms.cbn_transform.transform",
        "domain": "economics",
        "schedule": "0 3 * * 1",       # Weekly on Mondays @ 03:00 UTC
        "landing_dir": "cbn",
        "ingest_mode": "file",
        "options": {
            "publisher_id": "central-bank-of-nigeria",
            "publisher_title": "Central Bank of Nigeria",
            "source_name": "Central Bank of Nigeria, Statistics",
            "source_url": "https://statistics.cbn.gov.ng/",
        },
        "indicators": [
            {
                "id": "CBN_INTEREST_MPR",
                "name": "Monetary Policy Rate (MPR)",
                "excel_url": "https://www.cbn.gov.ng/Out/2023/STATISTICS/MPR.xlsx",
                "sheet": 0,
                "domain": "economics",
                "unit": "%",
                "col_map": {"Date": "period", "MPR (%)": "value"},
            },
            {
                "id": "CBN_FX_RESERVES",
                "name": "External Reserves",
                "excel_url": "https://www.cbn.gov.ng/Out/2023/STATISTICS/Reserves.xlsx",
                "sheet": 0,
                "domain": "economics",
                "unit": "USD (Billions)",
                "col_map": {"Date": "period", "Reserves": "value"},
            },
        ],
    },
    # Unstructured Track 2 (PDF / Report extraction)
    {
        "source_id": "NBS_Reports",
        "connector": "pipeline.connectors.generic.GenericFileConnector",
        "transform": "pipeline.transforms.generic_transform.generic_transform",
        "domain": "economics",
        "schedule": "0 4 * * 1",
        "landing_dir": "nbs_reports",
        "ingest_mode": "document",
        "indicators": [
            {
                "id": "NBS_CPI_REPORT_PDF",
                "name": "CPI Monthly Report (PDF)",
                "dataset_id": "NBS_CPI_PDF",
                "domain": "economics",
                "format": "pdf",
                "extract_tables": True,
            }
        ],
    },
    # World Bank World Development Indicators (JSON API, no key needed).
    # The listed indicators are the featured set. With options.discover on,
    # the connector also loads every other WDI indicator that has Nigeria
    # data (about 1,500 series exist in the catalogue; many are populated).
    {
        "source_id": "WorldBank",
        "connector": "pipeline.connectors.world_bank.WorldBankConnector",
        "transform": "pipeline.transforms.world_bank_transform.transform",
        "domain": "economy",
        "schedule": "0 1 * * 0",       # Weekly, Sundays @ 01:00 UTC
        "landing_dir": "world_bank",
        "ingest_mode": "api",
        "options": {
            "publisher_id": "world-bank",
            "publisher_title": "World Bank",
            "publisher_description": "World Development Indicators, the World Bank's main collection of development data.",
            "source_name": "World Bank, World Development Indicators",
            "source_url": "https://data.worldbank.org/country/nigeria",
            "license_id": "cc-by",
            "license_title": "Creative Commons Attribution 4.0 (CC BY 4.0)",
            "license_url": "https://datacatalog.worldbank.org/public-licenses",
            "country": "NGA",
            "discover": True,           # set False to load only the list below
            "max_indicators": None,     # cap discovery, e.g. 200 for a quick first run
            "request_delay_seconds": 0.25,
        },
        "indicators": [
            # code, name and domain. Units are read from the name's "(...)".
            {"id": "WB_NY_GDP_MKTP_CD",    "dataset_id": "NY.GDP.MKTP.CD",    "domain": "economy",        "name": "GDP (current US$)"},
            {"id": "WB_NY_GDP_MKTP_KD_ZG", "dataset_id": "NY.GDP.MKTP.KD.ZG", "domain": "economy",        "name": "GDP growth (annual %)"},
            {"id": "WB_NY_GDP_PCAP_CD",    "dataset_id": "NY.GDP.PCAP.CD",    "domain": "economy",        "name": "GDP per capita (current US$)"},
            {"id": "WB_FP_CPI_TOTL_ZG",    "dataset_id": "FP.CPI.TOTL.ZG",    "domain": "economy",        "name": "Inflation, consumer prices (annual %)"},
            {"id": "WB_SL_UEM_TOTL_ZS",    "dataset_id": "SL.UEM.TOTL.ZS",    "domain": "labour",         "name": "Unemployment, total (% of total labor force) (modeled ILO estimate)"},
            {"id": "WB_BX_TRF_PWKR_CD_DT", "dataset_id": "BX.TRF.PWKR.CD.DT", "domain": "economy",        "name": "Personal remittances, received (current US$)"},
            {"id": "WB_NE_EXP_GNFS_ZS",    "dataset_id": "NE.EXP.GNFS.ZS",    "domain": "economy",        "name": "Exports of goods and services (% of GDP)"},
            {"id": "WB_SP_POP_TOTL",       "dataset_id": "SP.POP.TOTL",       "domain": "population",     "name": "Population, total"},
            {"id": "WB_SP_URB_TOTL_IN_ZS", "dataset_id": "SP.URB.TOTL.IN.ZS", "domain": "population",     "name": "Urban population (% of total population)"},
            {"id": "WB_SP_DYN_TFRT_IN",    "dataset_id": "SP.DYN.TFRT.IN",    "domain": "population",     "name": "Fertility rate, total (births per woman)"},
            {"id": "WB_SP_DYN_LE00_IN",    "dataset_id": "SP.DYN.LE00.IN",    "domain": "health",         "name": "Life expectancy at birth, total (years)"},
            {"id": "WB_SH_DYN_MORT",       "dataset_id": "SH.DYN.MORT",       "domain": "health",         "name": "Mortality rate, under-5 (per 1,000 live births)"},
            {"id": "WB_SH_STA_MMRT",       "dataset_id": "SH.STA.MMRT",       "domain": "health",         "name": "Maternal mortality ratio (modeled estimate, per 100,000 live births)"},
            {"id": "WB_SH_H2O_BASW_ZS",    "dataset_id": "SH.H2O.BASW.ZS",    "domain": "health",         "name": "People using at least basic drinking water services (% of population)"},
            {"id": "WB_SE_PRM_ENRR",       "dataset_id": "SE.PRM.ENRR",       "domain": "education",      "name": "School enrollment, primary (% gross)"},
            {"id": "WB_SE_SEC_ENRR",       "dataset_id": "SE.SEC.ENRR",       "domain": "education",      "name": "School enrollment, secondary (% gross)"},
            {"id": "WB_SE_ADT_LITR_ZS",    "dataset_id": "SE.ADT.LITR.ZS",    "domain": "education",      "name": "Literacy rate, adult total (% of people ages 15 and above)"},
            {"id": "WB_EG_ELC_ACCS_ZS",    "dataset_id": "EG.ELC.ACCS.ZS",    "domain": "energy",         "name": "Access to electricity (% of population)"},
            {"id": "WB_IT_NET_USER_ZS",    "dataset_id": "IT.NET.USER.ZS",    "domain": "infrastructure", "name": "Individuals using the Internet (% of population)"},
            {"id": "WB_IT_CEL_SETS_P2",    "dataset_id": "IT.CEL.SETS.P2",    "domain": "infrastructure", "name": "Mobile cellular subscriptions (per 100 people)"},
            {"id": "WB_NV_AGR_TOTL_ZS",    "dataset_id": "NV.AGR.TOTL.ZS",    "domain": "agriculture",    "name": "Agriculture, forestry, and fishing, value added (% of GDP)"},
            {"id": "WB_AG_LND_ARBL_ZS",    "dataset_id": "AG.LND.ARBL.ZS",    "domain": "agriculture",    "name": "Arable land (% of land area)"},
        ],
    },
]


def seed_default_sources() -> int:
    """Insert or update baseline sources in cdm.data_sources.

    Returns:
        Number of sources seeded.
    """
    # Code owns the definition of a default source, so connector, schedule and
    # indicators are refreshed on every start. Two things an operator sets in
    # the database are kept:
    #   is_active  switching a source off must stick;
    #   options    keys already in the database win over the defaults below,
    #              so an override such as {"discover": false} survives, while
    #              option keys added in code later still appear.
    sql = text("""
        INSERT INTO cdm.data_sources (
            source_id, connector, transform, domain, schedule,
            landing_dir, ingest_mode, indicators, options, is_active
        ) VALUES (
            :source_id, :connector, :transform, :domain, :schedule,
            :landing_dir, :ingest_mode, CAST(:indicators AS JSONB),
            CAST(:options AS JSONB), :enabled
        )
        ON CONFLICT (source_id) DO UPDATE SET
            connector   = EXCLUDED.connector,
            transform   = EXCLUDED.transform,
            domain      = EXCLUDED.domain,
            schedule    = EXCLUDED.schedule,
            landing_dir = EXCLUDED.landing_dir,
            ingest_mode = EXCLUDED.ingest_mode,
            indicators  = EXCLUDED.indicators,
            options     = EXCLUDED.options || cdm.data_sources.options;
    """)

    seeded_count = 0
    engine = get_engine()
    with engine.begin() as conn:
        for source in DEFAULT_SOURCES:
            conn.execute(sql, {
                "source_id":   source["source_id"],
                "connector":   source["connector"],
                "transform":   source["transform"],
                "domain":      source["domain"],
                "schedule":    source["schedule"],
                "landing_dir": source["landing_dir"],
                "ingest_mode": source["ingest_mode"],
                "indicators":  json.dumps(source["indicators"]),
                "options":     json.dumps(source.get("options", {})),
                # Only decides whether a source starts switched on in a new
                # database; an existing row's is_active is never changed.
                "enabled":     bool(source.get("enabled", True)),
            })
            seeded_count += 1
            logger.info("Seeded source configuration: %s", source["source_id"])

    logger.info("Successfully seeded %d baseline data sources.", seeded_count)
    return seeded_count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed_default_sources()
