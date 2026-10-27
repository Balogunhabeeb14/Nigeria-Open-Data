"""Data quality validations applied to raw indicators before landing in the warehouse."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

logger = logging.getLogger(__name__)


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    name: str
    passed: bool
    severity: str          # 'CRITICAL' | 'WARNING' | 'INFO'
    message: str
    failed_count: int = 0  # rows that failed this check


@dataclass
class QualityReport:
    source: str
    indicator_id: str
    row_count: int
    results: list[CheckResult] = field(default_factory=list)

    @property
    def has_critical_failures(self) -> bool:
        return any(not r.passed and r.severity == "CRITICAL" for r in self.results)

    @property
    def has_warnings(self) -> bool:
        return any(not r.passed and r.severity == "WARNING" for r in self.results)

    def summary(self) -> str:
        lines = [f"Quality Report – {self.source}/{self.indicator_id} ({self.row_count} rows)"]
        for r in self.results:
            status = "✅ PASS" if r.passed else f"❌ {r.severity}"
            lines.append(f"  {status} | {r.name}: {r.message}")
        return "\n".join(lines)


# ── Individual check functions ────────────────────────────────────────────────

def check_required_columns(df: pd.DataFrame, required: list[str]) -> CheckResult:
    """Fail CRITICALLY if any required column is missing."""
    missing = [c for c in required if c not in df.columns]
    if missing:
        return CheckResult(
            name="required_columns",
            passed=False,
            severity="CRITICAL",
            message=f"Missing columns: {missing}",
        )
    return CheckResult(name="required_columns", passed=True, severity="INFO",
                       message="All required columns present")


def check_minimum_row_count(df: pd.DataFrame, min_rows: int = 1) -> CheckResult:
    """Fail CRITICALLY if the DataFrame is suspiciously empty."""
    if len(df) < min_rows:
        return CheckResult(
            name="min_row_count",
            passed=False,
            severity="CRITICAL",
            message=f"Only {len(df)} rows found; expected at least {min_rows}",
            failed_count=min_rows - len(df),
        )
    return CheckResult(name="min_row_count", passed=True, severity="INFO",
                       message=f"{len(df)} rows")


def check_no_nulls_in_key_columns(df: pd.DataFrame, key_cols: list[str]) -> CheckResult:
    """Warn if key columns (period, value) have nulls."""
    null_counts = {c: int(df[c].isna().sum()) for c in key_cols if c in df.columns}
    total_nulls = sum(null_counts.values())
    if total_nulls > 0:
        return CheckResult(
            name="key_column_nulls",
            passed=False,
            severity="WARNING",
            message=f"Nulls in key columns: {null_counts}",
            failed_count=total_nulls,
        )
    return CheckResult(name="key_column_nulls", passed=True, severity="INFO",
                       message="No nulls in key columns")


def check_value_range(
    df: pd.DataFrame,
    value_col: str,
    min_val: float | None = None,
    max_val: float | None = None,
) -> CheckResult:
    """Warn if numeric values fall outside an expected range."""
    if value_col not in df.columns:
        return CheckResult(name="value_range", passed=True, severity="INFO",
                           message=f"Column '{value_col}' not present; skipped")

    numeric = pd.to_numeric(df[value_col], errors="coerce")
    out_of_range = pd.Series([False] * len(numeric))

    if min_val is not None:
        out_of_range |= numeric < min_val
    if max_val is not None:
        out_of_range |= numeric > max_val

    failed = int(out_of_range.sum())
    if failed > 0:
        return CheckResult(
            name="value_range",
            passed=False,
            severity="WARNING",
            message=(
                f"{failed} values in '{value_col}' outside range "
                f"[{min_val}, {max_val}]"
            ),
            failed_count=failed,
        )
    return CheckResult(name="value_range", passed=True, severity="INFO",
                       message=f"All values in '{value_col}' within expected range")


def check_duplicate_periods(df: pd.DataFrame, period_col: str, geo_col: str | None = None) -> CheckResult:
    """Warn if the same period appears more than once for the same geography."""
    if period_col not in df.columns:
        return CheckResult(name="duplicate_periods", passed=True, severity="INFO",
                           message="Period column not present; skipped")

    subset = [period_col]
    if geo_col and geo_col in df.columns:
        subset.append(geo_col)

    dupes = int(df.duplicated(subset=subset).sum())
    if dupes > 0:
        return CheckResult(
            name="duplicate_periods",
            passed=False,
            severity="WARNING",
            message=f"{dupes} duplicate (period, geo) combinations found",
            failed_count=dupes,
        )
    return CheckResult(name="duplicate_periods", passed=True, severity="INFO",
                       message="No duplicate periods")


# ── Runner ────────────────────────────────────────────────────────────────────

class QualityRunner:
    """Orchestrates quality checks for a single indicator's raw DataFrame."""

    def __init__(self, source: str, indicator_id: str):
        self.source = source
        self.indicator_id = indicator_id

    def run(self, df: pd.DataFrame, indicator_config: dict) -> QualityReport:
        """Run all applicable checks and return a QualityReport.

        Args:
            df:               Raw DataFrame to validate.
            indicator_config: The indicator config dict from SOURCE_REGISTRY.
        """
        report = QualityReport(
            source=self.source,
            indicator_id=self.indicator_id,
            row_count=len(df),
        )

        col_map = indicator_config.get("col_map") or {}
        period_col = next((k for k, v in col_map.items() if v == "period"), "TIME_PERIOD")
        value_col  = next((k for k, v in col_map.items() if v == "value"),  "OBS_VALUE")

        # Always run these
        report.results.append(check_minimum_row_count(df, min_rows=1))

        if not df.empty:
            report.results.append(
                check_no_nulls_in_key_columns(df, [period_col, value_col])
            )
            report.results.append(
                check_duplicate_periods(df, period_col, geo_col="REF_AREA")
            )
            # Source-specific range rules
            value_range = indicator_config.get("value_range")
            if value_range:
                report.results.append(
                    check_value_range(df, value_col, *value_range)
                )

        logger.info(report.summary())
        return report
