"""DMO state debt: finding the documents and reading them, whatever their format."""
from __future__ import annotations

import io

import pytest

from pipeline.connectors import dmo
from pipeline.connectors.dmo import (
    DMOConnector,
    DMOParseError,
    document_text,
    parse_index,
    parse_report_date,
    parse_state_amounts,
    quarter_of,
)
from pipeline.geo import STATES, state_code
from pipeline.transforms.dmo_transform import transform

# Titles and addresses as they appear on dmo.gov.ng/debt-profile/sub-national-debts (read 2026-10-11).
INDEX_HTML = """
<table><tbody>
<tr><td><a href="/6079-states-and-fct-domestic-debt-stock-as-at-june-30-2026">States and FCT Domestic Debt Stock as at June 30, 2026</a></td></tr>
<tr><td><a href="/6084-states-fct-and-federal-government-s-external-debt-stock-as-at-june-30-2026">States, FCT and Federal Government's External Debt Stock as at June 30, 2026</a></td></tr>
<tr><td><a href="https://www.dmo.gov.ng/6001-states-and-fct-domestic-debt-stock-as-at-march-31-2026">States and FCT Domestic Debt Stock as at March 31, 2026</a></td></tr>
<tr><td><a href="/5207-36-states-fct-q4-2024-domestic-debt">States and FCT Domestic Debt Stock as at December 31, 2024</a></td></tr>
<tr><td><a href="/6001-states-and-fct-domestic-debt-stock-as-at-march-31-2026/file">States and FCT Domestic Debt Stock as at March 31, 2026</a></td></tr>
<tr><td><a href="/6101-nigeria-s-eurobonds-closing-prices/file">Nigeria's Eurobonds Closing Prices and Yields as at Thursday, October 8, 2026</a></td></tr>
<tr><td><a href="/about">About the DMO</a></td></tr>
</tbody></table>
"""

# First and last lines are the DMO's own figures for 31 March 2026; the middle is filled in for the test.
REAL_LINES = {
    "ABIA": 48_319_385_321.00, "ADAMAWA": 64_697_647_837.13, "AKWA IBOM": 83_627_874_451.56,
    "ANAMBRA": 9_616_754_025.27, "BAUCHI": 154_450_107_768.27, "BAYELSA": 50_167_068_717.72,
    "BENUE": 112_854_392_660.86, "BORNO": 88_435_569_669.48,
    "ZAMFARA": 47_477_140_118.87, "FCT": 389_875_138_075.16,
}


def document_lines(spellings: dict[str, str] | None = None, drop: tuple[str, ...] = ()) -> tuple[str, dict[str, float]]:
    """A document's text in the DMO's layout, and the amounts it holds by state code."""
    spellings = spellings or {}
    expected: dict[str, float] = {}
    lines = [
        "DOMESTIC DEBT DATA FOR THE 36 STATES OF THE FEDERATION AND THE FEDERAL CAPITAL TERRITORY AS AT MARCH 31ST, 2026",
        "PROVISIONAL        AMOUNT IN NAIRA",
        "SN STATE DEBT STOCK (N)",
    ]
    for number, (code, name) in enumerate(STATES.items(), start=1):
        label = "FCT" if code == "NG-FC" else name.upper()
        if label in drop:
            continue
        amount = REAL_LINES.get(label, 10_000_000_000.00 + number * 1_234_567.89)
        expected[code] = amount
        lines.append(f"{number} {spellings.get(label, label)} {amount:,.2f}")
    lines.append(f"Total {sum(expected.values()):,.2f}")
    lines += ["Important Notes", "2 The Domestic Debt Stock for Thirty Six (36) States of the Federation and the FCT were as at March 31, 2026"]
    return "\n".join(lines), expected


def test_index_keeps_one_domestic_debt_document_per_quarter():
    documents = parse_index(INDEX_HTML)
    assert [d["period"] for d in documents] == ["2026Q2", "2026Q1", "2024Q4"]         # newest first
    first = documents[1]
    assert first["url"] == "https://www.dmo.gov.ng/6001-states-and-fct-domestic-debt-stock-as-at-march-31-2026"
    assert first["file_url"] == first["url"] + "/file" and first["date"] == "2026-03-31"
    assert all("external" not in d["title"].lower() and "eurobond" not in d["title"].lower() for d in documents)


@pytest.mark.parametrize("title,expected", [
    ("States and FCT Domestic Debt Stock as at March 31, 2026", "2026Q1"),
    ("DOMESTIC DEBT DATA ... AS AT MARCH 31ST, 2026", "2026Q1"),
    ("States and FCT Domestic Debt Stock as at September 30 2023", "2023Q3"),
    ("States and FCT Domestic Debt Stock as at Dec 31, 2024", "2024Q4"),
])
def test_report_dates_become_quarters(title, expected):
    assert quarter_of(parse_report_date(title)) == expected


def test_titles_without_a_usable_date_are_ignored():
    assert parse_report_date("States and FCT Domestic Debt Stock") is None
    assert parse_report_date("External Debt Stock as at June 30, 2026") is None


def test_every_state_is_read_with_its_exact_amount():
    text, expected = document_lines()
    amounts, total = parse_state_amounts(text)
    assert amounts == expected and len(amounts) == 37
    assert amounts["NG-AB"] == 48_319_385_321.00 and amounts["NG-FC"] == 389_875_138_075.16
    assert total == pytest.approx(sum(expected.values()))


def test_other_spellings_and_look_alike_names():
    text, expected = document_lines(spellings={
        "AKWA IBOM": "AKWA-IBOM", "CROSS RIVER": "C/RIVER", "NASARAWA": "NASSARAWA",
        "FCT": "F.C.T", "NIGER": "Niger State",
    })
    amounts, _ = parse_state_amounts(text + "\nNIGERIA TOTAL PUBLIC DEBT 99,999,999,999,999.00")
    assert amounts == expected            # 'NIGERIA' is not Niger; nothing was overwritten


def test_serial_numbers_and_headings_are_not_amounts():
    amounts, total = parse_state_amounts("SN STATE DEBT STOCK (N)\n36 STATES AND THE FCT\n12 EDO\n13 EKITI 2,500,000.50")
    assert amounts == {"NG-EK": 2_500_000.50} and total is None


def test_excel_and_web_page_documents_are_read_too():
    from openpyxl import Workbook
    text, expected = document_lines()
    book = Workbook()
    sheet = book.active
    for code, amount in expected.items():
        sheet.append([None, STATES[code].upper() if code != "NG-FC" else "FCT", amount])
    buffer = io.BytesIO()
    book.save(buffer)
    assert parse_state_amounts(document_text(buffer.getvalue()))[0] == pytest.approx(expected)

    rows = "".join(f"<tr><td>{n}</td><td>{STATES[c].upper()}</td><td>{a:,.2f}</td></tr>" for n, (c, a) in enumerate(expected.items(), 1))
    html = f"<html><body><table>{rows}</table></body></html>".encode()
    assert parse_state_amounts(document_text(html))[0] == pytest.approx(expected)


@pytest.fixture
def connector(monkeypatch, tmp_path):
    """A DMO with three quarters published; the middle one is unreadable."""
    from pipeline.settings import settings
    monkeypatch.setattr(settings, "landing_root", tmp_path)
    monkeypatch.setattr(dmo.time, "sleep", lambda _: None)

    good, expected = document_lines()
    incomplete, _ = document_lines(drop=("KANO",))
    files = {"6079": good, "6001": "This page is temporarily unavailable.", "5207": incomplete}
    downloads: list[str] = []

    class Response:
        def __init__(self, text): self.text = text

    c = DMOConnector(config={"options": {"request_delay_seconds": 0}})

    def fake_get(url, **_):
        return Response(INDEX_HTML if "limitstart=0" in url else "<html></html>")

    def fake_download(url, dest):
        downloads.append(url)
        dest.write_bytes(f"<html><body><pre>{files[url.split('/')[3].split('-')[0]]}</pre></body></html>".encode())
        return dest

    monkeypatch.setattr(c, "_http_get", fake_get)
    monkeypatch.setattr(c, "_download_file", fake_download)
    c.downloads, c.expected = downloads, expected
    return c


def test_fetch_builds_the_state_by_quarter_table_and_skips_what_it_cannot_read(connector, caplog):
    df = connector.fetch({"id": "DMO_STATE_DOMESTIC_DEBT", "kind": "states"})

    assert sorted(df["TIME_PERIOD"].unique()) == ["2024Q4", "2026Q2"]       # 2026Q1 was unreadable
    latest = df[df["TIME_PERIOD"] == "2026Q2"]
    assert len(latest) == 37 and dict(zip(latest["REF_AREA"], latest["OBS_VALUE"])) == connector.expected
    assert latest["SOURCE_URL"].iloc[0].endswith("6079-states-and-fct-domestic-debt-stock-as-at-june-30-2026")
    older = df[df["TIME_PERIOD"] == "2024Q4"]
    assert len(older) == 36 and "NG-KN" not in set(older["REF_AREA"])       # loaded, with the gap visible
    assert "2026Q1" in caplog.text and "Kano" in caplog.text                # both problems were reported


def test_total_series_uses_the_documents_own_total_when_complete(connector):
    df = connector.fetch({"id": "DMO_STATES_DOMESTIC_DEBT_TOTAL", "kind": "total"})
    by_period = dict(zip(df["TIME_PERIOD"], df["OBS_VALUE"]))
    assert by_period["2026Q2"] == pytest.approx(sum(connector.expected.values()))
    assert set(df["REF_AREA"]) == {"NG"}
    incomplete = df[df["TIME_PERIOD"] == "2024Q4"].iloc[0]
    assert "Kano" in incomplete["NOTE"]                                       # a total missing a state says so


def test_past_quarters_are_not_downloaded_twice_but_recent_ones_are(connector, monkeypatch):
    monkeypatch.setattr(dmo, "_REFRESH_NEWEST", 1)
    connector.fetch({"kind": "states"})
    first = len(connector.downloads)
    connector.fetch({"kind": "states"})
    again = connector.downloads[first:]
    assert any("6079" in url for url in again)              # newest: always refreshed
    assert not any("5207" in url for url in again)          # an old, readable quarter: kept
    assert any("6001" in url for url in again)              # unreadable last time: tried again


def test_unreadable_document_raises_for_that_document_only(connector):
    with pytest.raises(DMOParseError, match="only 0 of 37"):
        connector.read_document({"title": "x", "period": "2026Q1", "file_url": "https://www.dmo.gov.ng/6001-x/file"})


def test_transform_gives_state_and_national_records(connector):
    states = transform(connector.fetch({"kind": "states"}), {"id": "DMO_STATE_DOMESTIC_DEBT", "name": "State debt", "unit": "naira"})
    lagos = next(r for r in states if r.geo_code == "NG-LA" and r.period == "2026Q2")
    assert (lagos.geo_level, lagos.geo_name, lagos.period_type, lagos.unit) == ("state", "Lagos", "quarter", "naira")
    assert lagos.source_system == "DMO" and lagos.raw_source_url.startswith("https://www.dmo.gov.ng/6079")
    total = transform(connector.fetch({"kind": "total"}), {"id": "T", "name": "Total"})
    assert {(r.geo_level, r.geo_code, r.geo_name) for r in total} == {("national", "NG", "Nigeria")}


@pytest.mark.parametrize("name,code", [
    ("AKWA-IBOM", "NG-AK"), ("Cross River State", "NG-CR"), ("NASSARAWA", "NG-NA"),
    ("F.C.T", "NG-FC"), ("Federal Capital Territory", "NG-FC"), ("lagos", "NG-LA"),
    ("Nigeria", None), ("", None),
])
def test_state_code(name, code):
    assert state_code(name) == code
