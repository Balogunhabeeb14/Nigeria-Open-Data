"""
pipeline/transforms/cdm.py
===========================
Common Data Model (CDM) definition.

CDMRecord is the single canonical representation of one data point
in the Nigeria Open Data platform.  Every connector's transform
function must produce a list of CDMRecord objects.

Why a dataclass?
  - Type-safe: Python will warn if you assign wrong types.
  - Easy to convert to dict for SQLAlchemy inserts.
  - Serves as living documentation of the CDM schema.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime


@dataclass
class CDMRecord:
    """One indicator observation in the Common Data Model.

    Maps 1-to-1 with a row in cdm.indicator_observation.
    """

    # ── Provenance ────────────────────────────────────────────────────────────
    source_system: str
    """Which system produced this data: 'CBN' | 'NigeriaDataPortal' | 'WorldBank'"""

    domain: str
    """Thematic domain: 'health' | 'economics' | 'agric'"""

    # ── Indicator identity ────────────────────────────────────────────────────
    indicator_id: str
    """Canonical indicator code, e.g. 'GDP_REAL', 'UNEMP_RATE', 'POP_TOTAL'"""

    indicator_name: str
    """Human-readable indicator name, e.g. 'Real Gross Domestic Product'"""

    # ── Geography ─────────────────────────────────────────────────────────────
    geo_level: str
    """Granularity: 'national' | 'state' | 'lga'"""

    geo_name: str
    """Readable place name: 'Nigeria' | 'Lagos' | 'Kano North'"""

    geo_code: str | None
    """ISO-3166 or NBS state code: 'NG' | 'NG-LA' | None"""

    # ── Time ──────────────────────────────────────────────────────────────────
    period_type: str
    """Temporal granularity: 'year' | 'quarter' | 'month'"""

    period: str
    """Period identifier: '2024' | '2024Q1' | '2024-01'"""

    # ── Observation ───────────────────────────────────────────────────────────
    value: float | None
    """The numeric measurement value"""

    unit: str | None
    """Measurement unit: '%' | 'Naira' | 'USD' | 'people'"""

    # ── Optional metadata ─────────────────────────────────────────────────────
    notes: str | None = None
    """Any caveats, revision flags, or source-specific notes"""

    raw_source_url: str | None = None
    """Original download URL or API endpoint (for audit trail)"""

    last_updated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )

    def to_dict(self) -> dict:
        """Convert to a plain dict suitable for SQLAlchemy insert."""
        d = asdict(self)
        # Ensure last_updated_at is a proper datetime (not string)
        if isinstance(d["last_updated_at"], str):
            d["last_updated_at"] = datetime.fromisoformat(d["last_updated_at"])
        return d

    def __repr__(self) -> str:
        return (
            f"CDMRecord({self.source_system}/{self.indicator_id} "
            f"geo={self.geo_code} period={self.period} value={self.value})"
        )


# ── Canonical indicator IDs ───────────────────────────────────────────────────
# Centralised so connectors and transforms reference constants, not magic strings.
class IndicatorID:
    GDP_REAL        = "GDP_REAL"
    GDP_NOMINAL     = "GDP_NOMINAL"
    UNEMP_RATE      = "UNEMP_RATE"
    POP_TOTAL       = "POP_TOTAL"
    AGRIC_GDP_SHARE = "AGRIC_GDP_SHARE"
    FOOD_PROD_IDX   = "FOOD_PROD_IDX"
    CBN_INTEREST_MPR = "CBN_INTEREST_MPR"
    CBN_MONEY_M2    = "CBN_MONEY_M2"
    CBN_FX_RESERVES = "CBN_FX_RESERVES"
    CBN_CPI_HEADLINE = "CBN_CPI_HEADLINE"


# ── Period type inference ─────────────────────────────────────────────────────

def infer_period_type(period_str: str) -> str:
    """Infer period_type from a period string.

    Examples:
        '2024'    → 'year'
        '2024Q1'  → 'quarter'
        '2024-01' → 'month'
        '2024-01-15' → 'month'   (day precision collapsed to month)
    """
    s = str(period_str).strip()
    if "Q" in s.upper():
        return "quarter"
    if len(s) >= 7 and s[4] == "-":
        return "month"
    return "year"
