"""Bounded file conversion. Uploaded content is data; never execute macros or formulas."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree

SUPPORTED_EXTENSIONS = (".csv", ".tsv", ".parquet", ".xlsx", ".json", ".jsonl", ".ndjson", ".pdf", ".docx", ".txt", ".md")
MAX_EXPANDED_BYTES = 100 * 1024 * 1024
MAX_DOCUMENT_PAGES = 500
MAX_TEXT_CHARS = 5_000_000


def _check_archive(data: bytes) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist()) > 10000 or sum(f.file_size for f in archive.infolist()) > MAX_EXPANDED_BYTES:
            raise ValueError("Office archive expands beyond the allowed size.")


def normalize_file(filename: str, data: bytes, max_rows: int, max_columns: int) -> tuple[str, bytes, list[str]]:
    """Convert supported formats to CSV while preserving document source locations."""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("Unsupported file type. Supported: " + ", ".join(SUPPORTED_EXTENSIONS))
    if suffix in (".csv", ".tsv", ".parquet"):
        return filename, data, []
    output = io.StringIO()
    writer = csv.writer(output)
    count = 0

    def write(row):
        nonlocal count
        count += 1
        if count > max_rows + 1 or len(row) > max_columns:
            raise ValueError("Converted file exceeds the row or column limit.")
        writer.writerow(row)
        if output.tell() > MAX_EXPANDED_BYTES:
            raise ValueError("Converted file exceeds the expanded size limit.")

    notices = []
    if suffix == ".xlsx":
        _check_archive(data)
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise ValueError('Excel support requires pip install -e ".[uploads]".') from exc
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
        try:
            if len(workbook.worksheets) != 1:
                raise ValueError("Upload one worksheet per XLSX file; export additional sheets separately.")
            sheet = workbook.worksheets[0]
            if (sheet.max_row or 0) > max_rows + 1 or (sheet.max_column or 0) > max_columns:
                raise ValueError("Worksheet exceeds the row or column limit.")
            for row in sheet.iter_rows(values_only=True):
                write(row)
            notices.append("XLSX uses saved cell values only; formulas are not executed. Unsaved formula results can be blank.")
        finally:
            workbook.close()
    elif suffix in (".json", ".jsonl", ".ndjson"):
        text = data.decode("utf-8-sig")
        records = json.loads(text) if suffix == ".json" else [json.loads(line) for line in text.splitlines() if line.strip()]
        if not isinstance(records, list) or not records or len(records) > max_rows:
            raise ValueError("JSON must contain a non-empty array of objects within the row limit.")
        keys = list(dict.fromkeys(k for row in records if isinstance(row, dict) for k in row))
        if not keys or len(keys) > max_columns or any(not isinstance(row, dict) for row in records):
            raise ValueError("JSON records must be objects within the column limit.")
        write(keys)
        for row in records:
            write([json.dumps(row[k], ensure_ascii=False) if isinstance(row.get(k), (dict, list)) else row.get(k) for k in keys])
    else:
        sections = []
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError as exc:
                raise ValueError('PDF support requires pip install -e ".[uploads]".') from exc
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise ValueError("Encrypted PDFs are unsupported. Upload an unlocked copy.")
            if len(reader.pages) > MAX_DOCUMENT_PAGES:
                raise ValueError("PDF exceeds the 500-page limit.")
            total_chars = 0
            for page_number, page in enumerate(reader.pages, 1):
                content = page.extract_text() or ""
                total_chars += len(content)
                if total_chars > MAX_TEXT_CHARS:
                    raise ValueError("Document text exceeds the extraction limit.")
                sections.append((f"page {page_number}", content))
            notices.append("PDF text extraction only; scanned images require OCR before upload.")
        elif suffix == ".docx":
            _check_archive(data)
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                xml = archive.read("word/document.xml")
            if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
                raise ValueError("XML entities are not allowed in documents.")
            root = ElementTree.fromstring(xml)
            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            sections = [(f"paragraph {i}", "".join(p.itertext()) if not list(p.iter(ns + "t")) else "".join(t.text or "" for t in p.iter(ns + "t"))) for i, p in enumerate(root.iter(ns + "p"), 1)]
            notices.append("DOCX body text and table paragraphs extracted; images, headers and embedded objects are not interpreted.")
        else:
            sections = [("text", data.decode("utf-8-sig"))]
        if sum(len(text) for _, text in sections) > MAX_TEXT_CHARS:
            raise ValueError("Document text exceeds the extraction limit.")
        write(["chunk_id", "source_name", "source_location", "body"])
        chunk_id = 0
        for location, text in sections:
            text = text.strip()
            for offset in range(0, len(text), 4000):
                chunk_id += 1
                write([chunk_id, Path(filename.replace("\\", "/")).name, location, text[offset:offset + 4000]])
        if not chunk_id:
            raise ValueError("No extractable text found. Scanned documents require OCR before upload.")
    return Path(filename).stem + ".csv", output.getvalue().encode("utf-8"), notices
