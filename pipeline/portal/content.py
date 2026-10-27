"""Bounded parsing in a separate, resource-limited process. No CDM coercion."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import multiprocessing
import os
import re
import tempfile
import zipfile
from datetime import date, datetime
from pathlib import Path

from pipeline.portal.remote import MAX_BYTES

MAX_ROWS = 25000
MAX_COLUMNS = 200
MAX_OUTPUT = 20 * 1024 * 1024
FORMATS = {"csv", "xlsx", "json", "pdf"}


def filename(value):
    if not value or value != Path(value).name or "/" in value or "\\" in value or any(ord(c) < 32 for c in value):
        raise ValueError("Use a plain filename without directories or control characters.")
    suffix = Path(value).suffix.lower().lstrip(".")
    if suffix not in FORMATS:
        raise ValueError("Supported files are CSV, XLSX, JSON and PDF.")
    return suffix


def validate(data, fmt):
    if not data or len(data) > MAX_BYTES:
        raise ValueError("Files must be non-empty and no larger than 50 MB.")
    if fmt == "pdf":
        if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-2048:]:
            raise ValueError("The file is not a complete PDF document.")
    elif fmt == "xlsx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > 2000 or sum(item.file_size for item in entries) > 100 * 1024 * 1024:
                    raise ValueError("The spreadsheet expands beyond the processing limit.")
                if any(item.file_size > 1024 * max(item.compress_size, 1) or ".." in Path(item.filename).parts for item in entries):
                    raise ValueError("The spreadsheet archive is unsafe.")
                names = archive.namelist()
                if "xl/workbook.xml" not in names or "[Content_Types].xml" not in names or any("vbaProject" in name for name in names):
                    raise ValueError("Only ordinary XLSX workbooks without macros are supported.")
        except zipfile.BadZipFile:
            raise ValueError("The file is not an XLSX workbook.") from None
    elif fmt in {"csv", "json"}:
        try:
            import codecs
            sample = codecs.getincrementaldecoder("utf-8-sig")().decode(data[:65536], final=False)
        except UnicodeDecodeError:
            raise ValueError("Text data must use UTF-8 encoding.") from None
        if "\x00" in sample or sample.lstrip().lower().startswith(("<!doctype", "<html", "<script", "<?xml")):
            raise ValueError("The file content does not match the selected text format.")
        if fmt == "json":
            try:
                json.loads(data)
            except (ValueError, UnicodeError):
                raise ValueError("The file is not valid UTF-8 JSON.") from None
    else:
        raise ValueError("This file format is not supported.")


def json_records(data, records_path=""):
    try:
        value = json.loads(data)
        for key in records_path.split(".") if records_path else []:
            value = value[key]
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise ValueError("JSON records were not found. Set a valid records path under Advanced settings.") from None
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("Supported JSON APIs return an array of flat objects, optionally at a records path. Other contracts need a connector.")
    return normalise(value)


def normalise(rows):
    if len(rows) > MAX_ROWS:
        raise ValueError("This dataset exceeds the 25,000-row processing limit.")
    columns = []
    for row in rows:
        for key, value in row.items():
            if not isinstance(key, str) or not key.strip() or len(key) > 200 or "\x00" in key:
                raise ValueError("Column names must be non-empty strings of at most 200 characters.")
            if isinstance(value, (list, dict)):
                raise ValueError("Nested cell values are unsupported. Use an API returning a flat table.")
            if isinstance(value, (datetime, date)):
                row[key] = value.isoformat()
            elif isinstance(value, float) and (value != value or abs(value) == float("inf")):
                raise ValueError("Numeric values must be finite.")
            elif value is not None and not isinstance(value, (str, int, float, bool)):
                row[key] = str(value)
            if isinstance(row[key], str) and (len(row[key]) > 10000 or "\x00" in row[key]):
                raise ValueError("A cell exceeds the processing limit.")
            if key not in columns:
                columns.append(key)
        if len(columns) > MAX_COLUMNS:
            raise ValueError("This dataset exceeds the 200-column processing limit.")
    if len(json.dumps(rows, allow_nan=False).encode()) > MAX_OUTPUT:
        raise ValueError("Extracted data exceeds the processing limit.")
    return rows


def formula(value):
    if not isinstance(value, str) or not value.lstrip().startswith(("=", "+", "-", "@")):
        return False
    try:
        float(value)
        return False
    except ValueError:
        return True


def _parse(data, fmt, records_path, mapping, output):
    try:
        # No credentials in the parser's environment. Production additionally needs
        # a restricted worker container; this is a resource boundary, not a VM sandbox.
        os.environ.clear()
        os.environ.update({"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"})
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
            if os.uname().sysname == "Linux":
                resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024,) * 2)
                if os.getuid() == 0:
                    os.setgroups([])
                    os.setgid(65534)
                    os.setuid(65534)
            resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT,) * 2)
        except ImportError:
            raise ValueError("File processing requires a Unix worker with resource limits.") from None
        validate(data, fmt)
        review = fmt == "pdf"
        if fmt == "json":
            rows = json_records(data, records_path)
        elif fmt == "csv":
            reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
            if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise ValueError("CSV headers must be present and unique.")
            rows = []
            for row in reader:
                if None in row or None in row.values():
                    raise ValueError("CSV rows must match the header's column count.")
                rows.append(row)
                if len(rows) > MAX_ROWS:
                    raise ValueError("This dataset exceeds the row limit.")
        elif fmt == "xlsx":
            import openpyxl
            book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
            if len(book.worksheets) != 1:
                review = True
            values = book.worksheets[0].iter_rows(values_only=True)
            header = next(values, ())
            if not header or len(header) > MAX_COLUMNS or any(value is None for value in header) or len(set(map(str, header))) != len(header):
                raise ValueError("The first worksheet needs non-empty, unique column headers.")
            rows = []
            for values_row in values:
                if all(value is None for value in values_row):
                    continue
                rows.append(dict(zip(map(str, header), values_row)))
                if len(rows) > MAX_ROWS:
                    raise ValueError("This spreadsheet exceeds the row limit.")
            book.close()
        else:
            import pdfplumber
            rows = []
            with pdfplumber.open(io.BytesIO(data)) as document:
                if len(document.pages) > 100:
                    raise ValueError("PDFs with more than 100 pages require a dedicated extraction workflow.")
                for page in document.pages:
                    for table in page.extract_tables():
                        if not table or len(table) < 2:
                            continue
                        header = [str(value).strip() if value else f"column_{i+1}" for i, value in enumerate(table[0])]
                        if len(header) != len(set(header)):
                            continue
                        rows.extend(dict(zip(header, values)) for values in table[1:])
                        if len(rows) > MAX_ROWS:
                            raise ValueError("Extracted PDF tables exceed the row limit.")
        rows = normalise(rows)
        if fmt != "pdf" and not rows:
            raise ValueError("No tabular records were found.")
        if mapping:
            existing = set().union(*(row.keys() for row in rows)) if rows else set()
            if not set(mapping) <= existing:
                raise ValueError("Column mapping refers to missing columns.")
            names = [mapping.get(key, key) for key in existing]
            if len(names) != len(set(names)):
                raise ValueError("Column mapping would create duplicate columns.")
            rows = [{mapping.get(key, key): value for key, value in row.items()} for row in rows]
        review |= any(formula(value) for row in rows for value in row.values())
        output.send({"rows": rows, "needs_review": review})
    except Exception:
        # Parser exceptions can contain raw data. Only a fixed diagnostic crosses
        # the boundary; malformed PDFs remain preserved for an operator to inspect.
        output.send({"error": "The document could not be safely parsed. Check its contents and processing limits."})
    finally:
        output.close()


def parse(data, fmt, records_path="", mapping=None):
    validate(data, fmt)
    context = multiprocessing.get_context("spawn")
    receiving, sending = context.Pipe(duplex=False)
    process = context.Process(target=_parse, args=(data, fmt, records_path, mapping or {}, sending))
    process.start()
    sending.close()
    try:
        if not receiving.poll(45):
            raise ValueError("File processing timed out. Use a smaller file or request operator review.")
        try:
            result = receiving.recv()
        except EOFError:
            raise ValueError("File processing exceeded its resource limits.") from None
        if "error" in result:
            raise ValueError(result["error"])
        return result
    finally:
        receiving.close()
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)


def save(root, dataset_id, data, fmt):
    validate(data, fmt)
    sha = hashlib.sha256(data).hexdigest()
    folder = Path(root) / "portal" / dataset_id
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = f"portal/{dataset_id}/{sha}.{fmt}"
    target = Path(root) / key
    if not target.exists():
        fd, temp = tempfile.mkstemp(dir=folder)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return {"storage_key": key, "sha256": sha, "size_bytes": len(data), "format": fmt}


def file_path(root, key):
    root = Path(root).resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root / "portal") or not path.is_file():
        raise ValueError("Stored file is unavailable.")
    return path


def csv_export(rows):
    columns = list(dict.fromkeys(key for row in rows for key in row))
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: f"'{value}" if formula(value) else value for key, value in row.items()})
    return stream.getvalue().encode()
